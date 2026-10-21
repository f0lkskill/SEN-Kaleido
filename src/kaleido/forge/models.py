"""forge 数据模型：生成请求与资源结果。"""

from pydantic import BaseModel, Field

from kaleido.profile.models.student import StudentAttributesInput


class GenerateRequest(BaseModel):
    """资源生成请求。

    二选一提供学生来源：``profile_id``（已建档）或 ``attributes``（临时预览）。
    """

    profile_id: str | None = None
    attributes: StudentAttributesInput | None = None
    resource_type: str  # 资源类型键，见 configs/forge/forge.yaml
    topic: str  # 教学主题
    extra: dict = Field(default_factory=dict)  # 补充要求
    source_resource_id: str | None = None  # 基于哪份原资源修订


class GeneratedResource(BaseModel):
    """生成结果（落库前的标准结构）。"""

    resource_id: str
    resource_type: str
    topic: str
    profile_id: str | None = None
    disability: str
    content: str
    prompt_template_key: str
    model: str
    usage: dict = Field(default_factory=dict)
    status: str = "draft"  # draft / approved / rejected
