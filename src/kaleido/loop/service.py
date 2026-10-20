"""loop 业务服务：把已审核证据汇总为评价快照。

规则：
- 只消费 ``verified`` 且已归类到学生的证据；
- 优先使用证据的 ``level`` 对应评分标准等级，其次使用 ``value`` 量化值；
- 没有可用分值的观测点计入缺失，不猜测、不补分；
- 维度/指标得分均为 0~1，保留两位小数，便于与画像指数对齐。
"""

from collections import defaultdict
from datetime import datetime

from kaleido.common.config import load_yaml
from kaleido.common.errors import NotFoundError
from kaleido.common.logging import get_logger
from kaleido.evidence.repository import EvidenceRepository
from kaleido.loop.models import EvaluationSnapshot, LoopEvaluateRequest
from kaleido.loop.repository import EvaluationRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault

logger = get_logger("loop.service")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


def _mean(values: list[float]) -> float:
    """求平均并保留两位小数。"""
    return round(sum(values) / len(values), 2)


class LoopService:
    """评价快照服务。"""

    def __init__(
        self,
        profile_service: ProfileService | None = None,
        evidence_repository: EvidenceRepository | None = None,
        vault: Vault | None = None,
        config: dict | None = None,
    ):
        self.vault = vault or Vault()
        self.config = config or load_yaml("loop", "loop")
        self.profile_service = profile_service or ProfileService()
        self.evidence = evidence_repository or EvidenceRepository(vault=self.vault)
        self.snapshots = EvaluationRepository(vault=self.vault)
        scoring = self.config.get("scoring") or {}
        self.value_scale = float(scoring.get("value_scale", 100))
        self.status_ok_coverage = float(scoring.get("status_ok_coverage", 1.0))
        self.max_evidence = int(scoring.get("max_evidence", 10000))

    def evaluate_student(
        self, student_id: str, request: LoopEvaluateRequest | None = None
    ) -> dict:
        """汇总学生已审核证据并落一条评价快照。"""
        if not student_id:
            raise NotFoundError("缺少学生 ID")
        profile = self.profile_service.get_student(student_id)
        framework = profile.get("framework") or {}
        verified = self._verified_evidence(student_id)
        by_observation: dict[str, list[dict]] = defaultdict(list)
        for item in verified:
            key = str(item.get("observation_key") or "")
            if key:
                by_observation[key].append(item)

        observation_scores: dict[str, float] = {}
        observation_counts: dict[str, int] = {}
        observation_names: dict[str, str] = {}
        observation_rubrics: dict[str, list] = {}
        indicator_scores: dict[str, float] = {}
        missing: list[str] = []
        all_observations = 0

        for indicator in framework.get("indicators") or []:
            scored_observations: list[float] = []
            for observation in indicator.get("observations") or []:
                all_observations += 1
                key = str(observation.get("key") or "")
                name = str(observation.get("name") or key)
                if key:
                    observation_names[key] = name
                    observation_rubrics[key] = list(observation.get("rubrics") or [])
                items = by_observation.get(key, [])
                scores = [
                    score
                    for item in items
                    if (score := self._score_item(item, observation)) is not None
                ]
                if not key or not scores:
                    if key:
                        missing.append(key)
                    continue
                observation_scores[key] = _mean(scores)
                observation_counts[key] = len(items)
                scored_observations.append(observation_scores[key])
            indicator_key = str(indicator.get("key") or "")
            if indicator_key and scored_observations:
                indicator_scores[indicator_key] = _mean(scored_observations)

        dimension_values: dict[str, list[float]] = defaultdict(list)
        for indicator in framework.get("indicators") or []:
            key = str(indicator.get("key") or "")
            dimension = str(indicator.get("dimension") or "")
            if dimension and key in indicator_scores:
                dimension_values[dimension].append(indicator_scores[key])
        dimension_scores = {
            dimension: _mean(values)
            for dimension, values in dimension_values.items()
            if values
        }
        weights = {
            str(key): float(value)
            for key, value in (framework.get("weights") or {}).items()
        }
        overall = self._overall_score(dimension_scores, weights)
        coverage = (
            round(len(observation_scores) / all_observations, 2)
            if all_observations
            else 0.0
        )
        if coverage >= self.status_ok_coverage:
            status = "ok"
        elif coverage > 0:
            status = "partial"
        else:
            status = "insufficient"

        now = _now()
        period = (request.period if request else None) or now[:7]
        snapshot = EvaluationSnapshot(
            snapshot_id=self.snapshots.next_id(),
            student_id=student_id,
            framework_id=str(framework.get("framework_id") or ""),
            period=period,
            status=status,
            dimension_scores=dimension_scores,
            indicator_scores=indicator_scores,
            observation_scores=observation_scores,
            observation_evidence_counts=observation_counts,
            observation_names=observation_names,
            coverage=coverage,
            missing_observations=missing,
            evidence_count=len(verified),
            scored_evidence_count=sum(
                1
                for item in verified
                if self._score_item(
                    item,
                    {
                        "rubrics": observation_rubrics.get(
                            str(item.get("observation_key") or ""), []
                        )
                    },
                )
                is not None
            ),
            evidence_ids=[
                str(item.get("evidence_id") or "")
                for item in verified
                if item.get("evidence_id")
            ],
            weights=weights,
            overall_score=overall,
            computed_at=now,
        )
        self.snapshots.save(snapshot)
        logger.info(
            "生成评价快照: student=%s snapshot=%s status=%s coverage=%s evidence=%d",
            student_id,
            snapshot.snapshot_id,
            status,
            coverage,
            len(verified),
        )
        return snapshot.model_dump()

    def latest(self, student_id: str) -> dict:
        """读取学生最近一次评价快照。"""
        return self.snapshots.latest(student_id).model_dump()

    def list_snapshots(
        self, student_id: str | None = None, page: int = 1, size: int = 20
    ) -> dict:
        """分页列出评价快照。"""
        items, total = self.snapshots.list(student_id, page=page, size=size)
        return {"total": total, "page": page, "size": size, "items": items}

    def get_snapshot(self, snapshot_id: str) -> dict:
        """读取指定快照。"""
        return self.snapshots.get(snapshot_id).model_dump()

    def _verified_evidence(self, student_id: str) -> list[dict]:
        """读取学生已审核、已归类的证据。"""
        items: list[dict] = []
        for item in self.evidence.iter_all():
            if item.get("student_id") != student_id:
                continue
            if item.get("status") != "verified":
                continue
            if item.get("scope") == "public":
                continue
            items.append(item)
            if len(items) >= self.max_evidence:
                break
        return items

    def _score_item(self, item: dict, observation: dict) -> float | None:
        """把单条证据转换为 0~1 分值；无法评分时返回 None。"""
        rubrics = observation.get("rubrics") or []
        levels = [int(rubric.get("level")) for rubric in rubrics if rubric.get("level") is not None]
        level = item.get("level")
        if level is not None and levels:
            try:
                value = int(level)
            except (TypeError, ValueError):
                value = None
            if value is not None and value in levels:
                # 等级在评分标准中的位置越靠后，得分越高
                ordered = sorted(set(levels))
                return round((ordered.index(value) + 1) / len(ordered), 4)
        value = item.get("value")
        if value is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if numeric < 0:
                return None
            if numeric <= 1:
                return round(min(1.0, numeric), 4)
            return round(min(1.0, numeric / self.value_scale), 4)
        return None

    @staticmethod
    def _overall_score(
        dimension_scores: dict[str, float], weights: dict[str, float]
    ) -> float | None:
        """按维度权重计算综合分；无权重时取算术平均。"""
        if not dimension_scores:
            return None
        weighted_total = 0.0
        weight_sum = 0.0
        for dimension, score in dimension_scores.items():
            weight = float(weights.get(dimension, 0.0))
            if weight > 0:
                weighted_total += score * weight
                weight_sum += weight
        if weight_sum > 0:
            return round(weighted_total / weight_sum, 2)
        return _mean(list(dimension_scores.values()))
