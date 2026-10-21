"""属性层：校验录入属性并解析默认值与适配约束。

负责把 :class:`StudentAttributesInput` 校验、补全为 :class:`StudentAttributes`：
- 按 ``attributes.yaml`` 校验枚举与必填项；
- 缺失的感官偏好按类型默认值推导；
- 从类型复制适配约束与 Prompt 模板键。
"""

from kaleido.common.errors import ConfigError, ValidationError
from kaleido.profile.config_loader import load_config
from kaleido.profile.models.student import StudentAttributes, StudentAttributesInput
from kaleido.profile.taxonomy import Taxonomy

# 允许类约束：任一障碍显式禁止即禁止，否则只要有一个障碍需要就保留
_PERMISSIVE_FLAGS = frozenset({"add_emoji", "visual_aid"})

# 历史版本遗留的篇幅/句长约束：不再进入生成或审查提示词
LEGACY_LENGTH_CONSTRAINTS = frozenset({"sentence_length_max", "short_sentence"})


def sanitize_constraints(constraints: dict | None) -> dict:
    """移除历史版本遗留的篇幅、字数或句长约束。"""
    return {
        key: value
        for key, value in (constraints or {}).items()
        if key not in LEGACY_LENGTH_CONSTRAINTS
    }


def _merge_constraints(taxonomy: Taxonomy, disabilities: list[str]) -> dict:
    """合并多障碍适配约束，避免后项覆盖前项导致安全约束失效。

    - 布尔约束默认取并集（任一障碍要求即生效）；允许类约束取交集；
    - 数值约束取最严格值（最小）；
    - 列表取并集；字符串等冲突保留主障碍（首项）的值。
    """
    merged: dict = {}
    for key in disabilities:
        for name, value in taxonomy.get(key).constraints.items():
            if name not in merged:
                merged[name] = value
                continue
            current = merged[name]
            if isinstance(current, bool) and isinstance(value, bool):
                if name in _PERMISSIVE_FLAGS:
                    merged[name] = current and value
                else:
                    merged[name] = current or value
            elif (
                isinstance(current, (int, float))
                and not isinstance(current, bool)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                merged[name] = min(current, value)
            elif isinstance(current, list) and isinstance(value, list):
                merged[name] = list(dict.fromkeys([*current, *value]))
    return merged


class AttributeSchema:
    """属性维度的校验规则与解析器。"""

    def __init__(
        self, spec: dict, level_order: list[str], pace_index_map: dict | None = None
    ):
        self.spec = spec  # 各属性的类型与取值约束
        self.level_order = level_order  # 认知等级从低到高的顺序
        self.pace_index_map = pace_index_map or {}  # 学习节奏 → 指数（0~1）

    @classmethod
    def load(cls) -> "AttributeSchema":
        """从配置文件加载属性校验规则。"""
        config = load_config("attributes")
        return cls(
            config.get("attributes", {}),
            config.get("cognitive_level_order", []),
            config.get("learning_pace_index", {}),
        )

    def validate(self, data: StudentAttributesInput) -> None:
        """校验录入属性是否满足必填与枚举约束。"""
        for field, rule in self.spec.items():
            value = getattr(data, field, None)
            # 必填校验
            if rule.get("required", False) and value in (None, [], ""):
                raise ValidationError(f"缺少必填属性: {field}")
            if value is None:
                continue
            allowed = rule.get("values", [])
            # 列表型属性逐项校验
            if rule.get("type") == "list":
                if not isinstance(value, list):
                    raise ValidationError(f"属性 {field} 应为列表")
                for item in value:
                    if allowed and item not in allowed:
                        raise ValidationError(f"属性 {field} 取值非法: {item}")
            # 枚举型属性整体校验
            elif allowed and value not in allowed:
                raise ValidationError(f"属性 {field} 取值非法: {value}")

    def resolve(
        self, taxonomy: Taxonomy, data: StudentAttributesInput
    ) -> StudentAttributes:
        """校验并补全属性，输出规范化结果。

        多障碍时：以首项为主障碍决定感官偏好与 Prompt 模板；
        适配约束按障碍顺序依次合并，后项覆盖同名字段。
        """
        self.validate(data)
        primary = data.disabilities[0]  # 主障碍：决定默认感官偏好与模板
        primary_type = taxonomy.get(primary)
        # 感官偏好：显式值优先，否则用主障碍类型默认值
        sensory = data.sensory_preference or primary_type.defaults.get("sensory_preference")
        if not sensory:
            raise ConfigError(f"类型 {primary} 未定义默认感官偏好")
        # 合并各障碍类型的适配约束（安全约束取并集，不受书写顺序影响）
        constraints = _merge_constraints(taxonomy, list(data.disabilities))
        return StudentAttributes(
            disabilities=list(data.disabilities),
            severity=data.severity,
            cognitive_level=data.cognitive_level,
            sensory_preference=sensory,
            rehab_goals=list(data.rehab_goals),
            learning_pace=data.learning_pace,
            baseline=data.baseline,
            # 合并后的适配约束，供生成层使用
            adaptation_constraints=constraints,
            prompt_template_key=primary_type.prompt_template,
            # 学习节奏指数：由节奏确定性映射，保留两位小数
            pace_index=round(float(self.pace_index_map.get(data.learning_pace, 0.5)), 2),
        )
