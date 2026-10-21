"""病症通用提示词规则集数据模型。"""

from typing import Literal

from pydantic import BaseModel

RuleStatus = Literal["pending", "approved", "rejected"]


class PromptRule(BaseModel):
    """一条由模型从资源质检中沉淀的病症通用规则。"""

    rule_id: str
    disability: str  # 规则归属的病症键，见 configs/profile/student_types.yaml
    text: str
    status: RuleStatus = "pending"  # pending / approved / rejected
    source_resource_id: str | None = None  # 来源资源
    source_topic: str = ""
    source_score: int | None = None
    source_profile_id: str | None = None  # 来源学生（仅用于追溯，不参与生成）
    model: str = ""
    created_at: str = ""
    updated_at: str = ""


class PromptRuleUpdateRequest(BaseModel):
    """审核规则：通过或拒绝。"""

    status: RuleStatus
