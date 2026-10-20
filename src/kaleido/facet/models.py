"""facet 数据模型：质量校验请求与报告。"""

from typing import Literal

from pydantic import BaseModel, Field


class FacetEvaluationRequest(BaseModel):
    """资源质量校验请求。"""

    use_llm: bool = True  # 是否调用云端模型做适配度评分
    force: bool = False  # 保留字段：为后续强制重新校验预留


class FacetRuleIssue(BaseModel):
    """规则命中项。"""

    code: str
    level: Literal["error", "warning"]
    message: str
    suggestion: str = ""


class FacetDimension(BaseModel):
    """单个评分维度。"""

    key: str
    name: str
    weight: float
    score: int | None = None


class FacetReport(BaseModel):
    """一次质量校验的完整报告。"""

    resource_id: str
    profile_id: str | None = None
    verdict: Literal["pass", "review", "fail"]
    score: int
    rule_score: int
    blocking: bool = False
    rules: dict = Field(default_factory=dict)
    dimensions: list[FacetDimension] = Field(default_factory=list)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    llm: dict | None = None
    use_llm: bool = True
    model: str = ""
    usage: dict = Field(default_factory=dict)
    evaluated_at: str = ""
