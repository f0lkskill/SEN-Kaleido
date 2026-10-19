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

    def __init__(self, spec: dict, level_order: list[str]):
        self.spec = spec  # 各属性的类型与取值约束
        self.level_order = level_order  # 认知等级从低到高的顺序

    @classmethod
    def load(cls) -> "AttributeSchema":
        """从配置文件加载属性校验规则。"""
        config = load_config("attributes")
        return cls(config.get("attributes", {}), config.get("cognitive_level_order", []))

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
        """校验并补全属性，输出规范化结果。"""
        self.validate(data)
        student_type = taxonomy.get(data.disability)
        # 感官偏好：显式值优先，否则用类型默认值
        sensory = data.sensory_preference or student_type.defaults.get("sensory_preference")
        if not sensory:
            raise ConfigError(f"类型 {data.disability} 未定义默认感官偏好")
        return StudentAttributes(
            disability=data.disability,
            severity=data.severity,
            cognitive_level=data.cognitive_level,
            sensory_preference=sensory,
            rehab_goals=list(data.rehab_goals),
            learning_pace=data.learning_pace,
            baseline=data.baseline,
            # 从类型定义复制适配约束，供生成层使用
            adaptation_constraints=dict(student_type.constraints),
            prompt_template_key=student_type.prompt_template,
        )
