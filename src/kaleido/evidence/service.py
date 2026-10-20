"""证据业务服务。

核心约束（与评价框架的设计原则一致）：
- 公有证据尚未归属学生，可作为待归类素材先入库；
- 归类证据必须挂在真实学生与真实观测点上；
- 来源类型必须已登记，且被该观测点声明；
- 原始媒体（如视频）在归类前必须先转为结构化事件；
- 教师草稿经审核后才能作为已确认证据使用。
"""

from collections.abc import Callable
from datetime import datetime

from kaleido.common.errors import NotFoundError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.evidence.models import (
    EVIDENCE_SCOPES,
    EVIDENCE_STATUSES,
    MEDIA_IMAGE,
    MEDIA_TEXT,
    MEDIA_TYPES,
    MEDIA_VIDEO,
    SCOPE_CLASSIFIED,
    SCOPE_PUBLIC,
    STATUS_DRAFT,
    STATUS_REJECTED,
    STATUS_VERIFIED,
    ClassifyEvidenceRequest,
    CreateEvidenceRequest,
    EvidenceRecord,
    ReviewEvidenceRequest,
    UpdateEvidenceRequest,
)
from kaleido.evidence.repository import EvidenceRepository
from kaleido.profile.config_loader import load_config
from kaleido.profile.models.evaluation import ObservationItem, StudentEvaluationProfile
from kaleido.profile.repository import StudentRepository

logger = get_logger("evidence.service")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


class EvidenceService:
    """证据管理业务服务。"""

    def __init__(
        self,
        repository=None,
        student_repository=None,
        on_verified: Callable[[str], None] | None = None,
    ):
        # 依赖可注入；测试时传入指向临时目录的仓库
        self.repository = repository or EvidenceRepository()
        self.students = student_repository or StudentRepository()
        # 证据审核通过后的回调（统一入口用于自动投递 loop.evaluate）
        self.on_verified = on_verified

    def _source_defs(self) -> dict:
        """读取证据来源定义（随配置热重载更新）。"""
        return load_config("evidence_sources").get("evidence_sources", {})

    def _student(self, student_id: str) -> StudentEvaluationProfile:
        """读取学生档案；不存在时转为更明确的参数错误。"""
        try:
            return self.students.get(student_id)
        except NotFoundError:
            raise ValidationError(f"学生不存在: {student_id}") from None

    @staticmethod
    def _observation(profile: StudentEvaluationProfile, observation_key: str) -> ObservationItem:
        """在学生框架中定位观测点。"""
        for indicator in profile.framework.indicators:
            for observation in indicator.observations:
                if observation.key == observation_key:
                    return observation
        raise ValidationError(f"观测点不属于该学生的评价框架: {observation_key}")

    @staticmethod
    def _source(sources: dict, source_type: str) -> dict:
        """校验并返回来源定义。"""
        source = sources.get(source_type)
        if source is None:
            raise ValidationError(f"未知证据来源: {source_type}")
        return source

    @staticmethod
    def _normalize_scope(scope: str | None, student_id: str, observation_key: str) -> str:
        """确定公有/归类归属，并校验字段组合。"""
        if scope:
            if scope not in EVIDENCE_SCOPES:
                raise ValidationError(f"未知证据归属: {scope}")
            value = scope
        else:
            value = SCOPE_CLASSIFIED if student_id else SCOPE_PUBLIC
        if value == SCOPE_PUBLIC:
            if student_id or observation_key:
                raise ValidationError("公有证据不能关联学生或观测点")
        elif not student_id or not observation_key:
            raise ValidationError("归类证据必须指定学生与观测点")
        return value

    @staticmethod
    def _validate_media(media_type: str, content: str, attachments: list[str]) -> None:
        """校验媒体类型与必要内容。"""
        if media_type not in MEDIA_TYPES:
            raise ValidationError(f"未知媒体类型: {media_type}")
        if media_type == MEDIA_TEXT and not content.strip() and not attachments:
            raise ValidationError("文本证据需要填写内容或上传文本文件")
        if media_type in (MEDIA_IMAGE, MEDIA_VIDEO) and not attachments:
            raise ValidationError("图像/视频证据需要先上传附件")

    def create(self, request: CreateEvidenceRequest) -> dict:
        """新增证据草稿：公有证据可直接入库，归类证据需通过观测点校验。"""
        scope = self._normalize_scope(
            request.scope,
            request.student_id,
            request.observation_key,
        )
        sources = self._source_defs()
        source = self._source(sources, request.source_type)
        self._validate_media(request.media_type, request.content, list(request.attachments))

        observation: ObservationItem | None = None
        if scope == SCOPE_CLASSIFIED:
            profile = self._student(request.student_id)
            observation = self._observation(profile, request.observation_key)
            if observation.evidence_sources and request.source_type not in observation.evidence_sources:
                raise ValidationError(
                    f"观测点 {observation.key} 不接受证据来源 {request.source_type}"
                )
            # 原始媒体必须先结构化，禁止把未切段视频直接作为已归类证据
            if source.get("requires_segmentation") and not request.content.strip():
                raise ValidationError("视频事件需先转为结构化描述（时间戳 + 行为标签）")

        default_title = observation.name if observation else str(source.get("name") or "未命名证据")
        now = _now()
        record = EvidenceRecord(
            evidence_id=self.repository.next_id(),
            scope=scope,
            student_id=request.student_id,
            observation_key=request.observation_key,
            source_type=request.source_type,
            media_type=request.media_type,
            title=request.title or default_title,
            content=request.content,
            value=request.value,
            level=request.level,
            attachments=list(request.attachments),
            collected_at=request.collected_at or now,
            collector=request.collector,
            note=request.note,
            status=STATUS_DRAFT,
            created_at=now,
            updated_at=now,
        )
        self.repository.save(record)
        logger.info(
            "新增证据: id=%s scope=%s student=%s observation=%s source=%s media=%s",
            record.evidence_id,
            record.scope,
            record.student_id,
            record.observation_key,
            record.source_type,
            record.media_type,
        )
        return record.model_dump()

    def get(self, evidence_id: str) -> dict:
        """读取单条证据。"""
        return self.repository.get(evidence_id).model_dump()

    def list(
        self,
        student_id: str | None = None,
        observation_key: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        media_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按条件分页列出证据，按采集时间倒序。"""
        if status and status not in EVIDENCE_STATUSES:
            raise ValidationError(f"未知证据状态: {status}")
        if scope and scope not in EVIDENCE_SCOPES:
            raise ValidationError(f"未知证据归属: {scope}")
        if media_type and media_type not in MEDIA_TYPES:
            raise ValidationError(f"未知媒体类型: {media_type}")
        filters = {
            key: value
            for key, value in (
                ("student_id", student_id),
                ("observation_key", observation_key),
                ("source_type", source_type),
                ("status", status),
                ("scope", scope),
                ("media_type", media_type),
            )
            if value
        }
        items, total = self.repository.list(filters, page=page, size=size)
        items.sort(key=lambda item: str(item.get("collected_at") or ""), reverse=True)
        return {"total": total, "page": page, "size": size, "items": items}

    def update(self, evidence_id: str, request: UpdateEvidenceRequest) -> dict:
        """更新证据内容；已审核通过的证据需先驳回。"""
        record = self.repository.get(evidence_id)
        if record.status == STATUS_VERIFIED:
            raise ValidationError("已审核证据不可直接修改，请先驳回")
        updates = request.model_dump(exclude_unset=True)
        media_type = updates.get("media_type")
        if media_type is not None and media_type not in MEDIA_TYPES:
            raise ValidationError(f"未知媒体类型: {media_type}")
        for field, value in updates.items():
            setattr(record, field, value)
        record.updated_at = _now()
        self.repository.save(record)
        logger.info("更新证据: id=%s", evidence_id)
        return record.model_dump()

    def classify(self, evidence_id: str, request: ClassifyEvidenceRequest) -> dict:
        """把公有证据归类到学生与观测点；已归类证据也可重新指定所有者。"""
        record = self.repository.get(evidence_id)
        sources = self._source_defs()
        source_type = request.source_type or record.source_type
        source = self._source(sources, source_type)
        profile = self._student(request.student_id)
        observation = self._observation(profile, request.observation_key)
        if observation.evidence_sources and source_type not in observation.evidence_sources:
            raise ValidationError(
                f"观测点 {observation.key} 不接受证据来源 {source_type}"
            )
        if source.get("requires_segmentation") and not record.content.strip():
            raise ValidationError("视频事件需先转为结构化描述（时间戳 + 行为标签）")
        self._validate_media(record.media_type, record.content, list(record.attachments))

        now = _now()
        record.scope = SCOPE_CLASSIFIED
        record.student_id = request.student_id
        record.observation_key = request.observation_key
        record.source_type = source_type
        if request.title is not None and request.title.strip():
            record.title = request.title.strip()
        elif not record.title or record.title == str(source.get("name")):
            record.title = observation.name
        record.updated_at = now
        self.repository.save(record)
        logger.info(
            "归类证据: id=%s student=%s observation=%s source=%s",
            evidence_id,
            record.student_id,
            record.observation_key,
            record.source_type,
        )
        return record.model_dump()

    def review(self, evidence_id: str, request: ReviewEvidenceRequest) -> dict:
        """审核通过或驳回证据。"""
        if request.status not in (STATUS_VERIFIED, STATUS_REJECTED):
            raise ValidationError("审核结果只能是 verified 或 rejected")
        record = self.repository.get(evidence_id)
        now = _now()
        record.status = request.status
        record.verified_by = request.verified_by
        record.verified_at = now
        if request.note:
            record.note = request.note
        record.updated_at = now
        self.repository.save(record)
        logger.info(
            "审核证据: id=%s status=%s by=%s",
            evidence_id,
            request.status,
            request.verified_by,
        )
        # 审核通过后自动触发学情评价；回调失败不影响证据审核本身
        if (
            request.status == STATUS_VERIFIED
            and record.student_id
            and self.on_verified is not None
        ):
            try:
                self.on_verified(record.student_id)
            except Exception:
                logger.exception("证据审核后自动触发 loop 失败: student=%s", record.student_id)
        return record.model_dump()

    def delete(self, evidence_id: str) -> dict:
        """删除证据。"""
        self.repository.delete(evidence_id)
        logger.info("删除证据: id=%s", evidence_id)
        return {"evidence_id": evidence_id}

    def summary(self, student_id: str | None = None, scope: str | None = None) -> dict:
        """按状态/归属/媒体/来源/观测点汇总证据数量。"""
        if scope and scope not in EVIDENCE_SCOPES:
            raise ValidationError(f"未知证据归属: {scope}")
        filters = {}
        if student_id:
            filters["student_id"] = student_id
        if scope:
            filters["scope"] = scope
        items, _ = self.repository.list(filters or None, page=1, size=1000000)
        by_status = {status: 0 for status in EVIDENCE_STATUSES}
        by_scope = {item: 0 for item in EVIDENCE_SCOPES}
        by_media: dict[str, int] = {}
        by_source: dict[str, int] = {}
        by_observation: dict[str, int] = {}
        for item in items:
            status = str(item.get("status") or STATUS_DRAFT)
            by_status[status] = by_status.get(status, 0) + 1
            item_scope = str(
                item.get("scope")
                or (SCOPE_CLASSIFIED if item.get("student_id") else SCOPE_PUBLIC)
            )
            by_scope[item_scope] = by_scope.get(item_scope, 0) + 1
            media = str(item.get("media_type") or MEDIA_TEXT)
            by_media[media] = by_media.get(media, 0) + 1
            source = str(item.get("source_type") or "")
            by_source[source] = by_source.get(source, 0) + 1
            observation = str(item.get("observation_key") or "")
            if observation:
                by_observation[observation] = by_observation.get(observation, 0) + 1
        return {
            "total": len(items),
            "by_status": by_status,
            "by_scope": by_scope,
            "by_media": by_media,
            "by_source": by_source,
            "by_observation": by_observation,
        }
