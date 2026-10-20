"""loop 数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class LoopEvaluateRequest(BaseModel):
    """触发一次评价快照计算。"""

    period: str | None = None  # 评价周期标签，缺省为当前年月（如 2026-10）


class EvaluationSnapshot(BaseModel):
    """一次证据驱动的评价快照。"""

    snapshot_id: str
    student_id: str
    framework_id: str = ""
    period: str = ""
    status: Literal["ok", "partial", "insufficient"] = "insufficient"
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    indicator_scores: dict[str, float] = Field(default_factory=dict)
    observation_scores: dict[str, float] = Field(default_factory=dict)
    observation_evidence_counts: dict[str, int] = Field(default_factory=dict)
    observation_names: dict[str, str] = Field(default_factory=dict)
    coverage: float = 0.0
    missing_observations: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    scored_evidence_count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    overall_score: float | None = None
    source: str = "evidence"
    computed_at: str = ""
