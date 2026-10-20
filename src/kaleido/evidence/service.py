"""证据业务服务。

核心约束（与评价框架的设计原则一致）：
- 证据必须挂在真实学生与真实观测点上；
- 来源类型必须已登记，且被该观测点声明；
- 原始媒体（如视频）必须先转为结构化事件；
- 教师草稿经审核后才能作为已确认证据使用。
"""

from datetime import datetime

from kaleido.common.errors import NotFoundError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.evidence.models import (
    EVIDENCE_STATUSES,
    STATUS_DRAFT,
    STATUS_REJECTED,
    STATUS_VERIFIED,
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

    def __init__(self, repository=None, student_repository=None):
        # 依赖可注入；测试时传入指向临时目录的仓库
        self.repository = repository or EvidenceRepository()
        self.students = student_repository or StudentRepository()

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

    def create(self, request: CreateEvidenceRequest) -> dict:
        """新增证据草稿。"""
        profile = self._student(request.student_id)
        observation = self._observation(profile, request.observation_key)
        sources = self._source_defs()
        source = sources.get(request.source_type)
        if source is None:
            raise ValidationError(f"未知证据来源: {request.source_type}")
        if observation.evidence_sources and request.source_type not in observation.evidence_sources:
            raise ValidationError(
                f"观测点 {observation.key} 不接受证据来源 {request.source_type}"
            )
        # 原始媒体必须先结构化，禁止把未切段视频直接作为证据
        if source.get("requires_segmentation") and not request.content.strip():
            raise ValidationError("视频事件需先转为结构化描述（时间戳 + 行为标签）")

        now = _now()
        record = EvidenceRecord(
            evidence_id=self.repository.next_id(),
            student_id=request.student_id,
            observation_key=request.observation_key,
            source_type=request.source_type,
            title=request.title or observation.name,
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
            "新增证据: id=%s student=%s observation=%s source=%s",
            record.evidence_id,
            record.student_id,
            record.observation_key,
            record.source_type,
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
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按条件分页列出证据，按采集时间倒序。"""
        if status and status not in EVIDENCE_STATUSES:
            raise ValidationError(f"未知证据状态: {status}")
        filters = {
            key: value
            for key, value in (
                ("student_id", student_id),
                ("observation_key", observation_key),
                ("source_type", source_type),
                ("status", status),
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
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(record, field, value)
        record.updated_at = _now()
        self.repository.save(record)
        logger.info("更新证据: id=%s", evidence_id)
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
        return record.model_dump()

    def delete(self, evidence_id: str) -> dict:
        """删除证据。"""
        self.repository.delete(evidence_id)
        logger.info("删除证据: id=%s", evidence_id)
        return {"evidence_id": evidence_id}

    def summary(self, student_id: str | None = None) -> dict:
        """按状态/来源/观测点汇总证据数量。"""
        filters = {"student_id": student_id} if student_id else None
        items, _ = self.repository.list(filters, page=1, size=1000000)
        by_status = {status: 0 for status in EVIDENCE_STATUSES}
        by_source: dict[str, int] = {}
        by_observation: dict[str, int] = {}
        for item in items:
            status = str(item.get("status") or STATUS_DRAFT)
            by_status[status] = by_status.get(status, 0) + 1
            source = str(item.get("source_type") or "")
            by_source[source] = by_source.get(source, 0) + 1
            observation = str(item.get("observation_key") or "")
            by_observation[observation] = by_observation.get(observation, 0) + 1
        return {
            "total": len(items),
            "by_status": by_status,
            "by_source": by_source,
            "by_observation": by_observation,
        }
