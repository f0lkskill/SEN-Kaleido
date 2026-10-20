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
        # 依次合并各障碍类型的适配约束
        constraints: dict = {}
        for key in data.disabilities:
            constraints.update(taxonomy.get(key).constraints)
        # 视觉参照与表情符号冲突时，以无障碍约束优先
        if constraints.get("avoid_visual_ref"):
            constraints["add_emoji"] = False
            constraints["visual_aid"] = False
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
