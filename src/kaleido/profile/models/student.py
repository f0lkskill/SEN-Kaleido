"""属性层数据模型。

区分两类：
- :class:`StudentAttributesInput`：建档时录入，允许缺省（如感官偏好可留空由规则推导）；
- :class:`StudentAttributes`：规范化后的结果，字段完整，并携带推导出的适配约束。
"""

from pydantic import BaseModel, Field


class StudentAttributesInput(BaseModel):
    """学生属性录入（输入）。感官偏好与康复目标可缺省。"""

    disabilities: list[str]  # 障碍类型（可多选，至少一项）
    severity: str  # 障碍程度：mild / moderate / severe
    cognitive_level: str  # 认知等级
    sensory_preference: str | None = None  # 感官偏好，缺省则由类型规则推导
    rehab_goals: list[str] = Field(default_factory=list)  # 康复目标（可多选）
    learning_pace: str  # 学习节奏：fast / medium / slow
    baseline: dict | None = None  # 动态能力基线快照


class StudentAttributes(BaseModel):
    """规范化后的学生属性（输出）。字段完整，附带推导结果。"""

    disabilities: list[str]  # 障碍类型（多障碍时为多项，首项视为主障碍）
    severity: str
    cognitive_level: str
    sensory_preference: str  # 已解析（显式值或类型默认值）
    rehab_goals: list[str] = Field(default_factory=list)
    learning_pace: str
    baseline: dict | None = None
    adaptation_constraints: dict = Field(default_factory=dict)  # 推导出的适配约束
    prompt_template_key: str = ""  # 推导出的 Prompt 模板键
    pace_index: float = 0.0  # 学习节奏指数（0~1，由节奏确定性推导）


class CreateStudentRequest(BaseModel):
    """建立学生的请求体。"""

    client_request_id: str | None = None  # 幂等请求 ID，用于去重
    name: str  # 学生姓名/化名
    attributes: StudentAttributesInput  # 属性录入
    generate_framework: bool = True  # 是否同时生成评价框架


class UpdateStudentRequest(BaseModel):
    """更新学生的请求体，字段均可缺省，只更新传入的部分。"""

    name: str | None = None
    attributes: StudentAttributesInput | None = None
