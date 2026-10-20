"""证据数据模型。

一条证据对应「学生 × 观测点 × 来源类型 × 采集时间」的一次记录；
也允许尚未归属学生的公有证据先入库，之后再归类到学生。
审核状态用于区分教师草稿与已确认数据。
"""

from pydantic import BaseModel, Field

# 证据归属：public 为未归类公有证据，classified 为已划分所有者
SCOPE_PUBLIC = "public"
SCOPE_CLASSIFIED = "classified"
EVIDENCE_SCOPES = (SCOPE_PUBLIC, SCOPE_CLASSIFIED)

# 证据媒体类型
MEDIA_TEXT = "text"
MEDIA_IMAGE = "image"
MEDIA_VIDEO = "video"
MEDIA_TYPES = (MEDIA_TEXT, MEDIA_IMAGE, MEDIA_VIDEO)

# 证据审核状态
STATUS_DRAFT = "draft"
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"
EVIDENCE_STATUSES = (STATUS_DRAFT, STATUS_VERIFIED, STATUS_REJECTED)


class EvidenceRecord(BaseModel):
    """一条证据记录。"""

    evidence_id: str  # 证据 ID，格式 e_00001
    scope: str = SCOPE_CLASSIFIED  # public / classified
    student_id: str = ""  # 关联学生档案 ID；公有证据为空
    observation_key: str = ""  # 关联评价框架观测点；公有证据为空
    source_type: str  # 证据来源类型键（见 evidence_sources.yaml）
    media_type: str = MEDIA_TEXT  # text / image / video
    title: str = ""  # 标题，默认取观测点或来源名称
    content: str = ""  # 文本描述/评语/结构化事件
    value: float | None = None  # 量化值（如得分、时长、正确率）
    level: int | None = None  # 对应评分标准的等级序号
    attachments: list[str] = Field(default_factory=list)  # 附件引用（URL/路径）
    collected_at: str = ""  # 采集时间（ISO 字符串）
    collector: str = ""  # 采集人
    note: str = ""  # 审核意见或补充说明
    status: str = STATUS_DRAFT  # draft / verified / rejected
    verified_by: str = ""  # 审核人
    verified_at: str | None = None  # 审核时间
    created_at: str | None = None
    updated_at: str | None = None


class CreateEvidenceRequest(BaseModel):
    """新增证据请求；公有证据可不传学生与观测点。"""

    scope: str | None = None  # 缺省按是否提供学生自动判定
    student_id: str = ""
    observation_key: str = ""
    source_type: str
    media_type: str = MEDIA_TEXT
    title: str = ""
    content: str = ""
    value: float | None = None
    level: int | None = None
    attachments: list[str] = Field(default_factory=list)
    collected_at: str | None = None  # 缺省为当前时间
    collector: str = ""
    note: str = ""


class UpdateEvidenceRequest(BaseModel):
    """更新证据请求（仅草稿/被驳回状态可改）。"""

    media_type: str | None = None
    title: str | None = None
    content: str | None = None
    value: float | None = None
    level: int | None = None
    attachments: list[str] | None = None
    collected_at: str | None = None
    collector: str | None = None
    note: str | None = None


class ClassifyEvidenceRequest(BaseModel):
    """把公有证据归类到学生与观测点。"""

    student_id: str
    observation_key: str
    source_type: str | None = None  # 缺省沿用原来源
    title: str | None = None  # 缺省沿用原标题


class ReviewEvidenceRequest(BaseModel):
    """审核证据请求。"""

    status: str  # 仅允许 verified / rejected
    verified_by: str = ""
    note: str = ""
