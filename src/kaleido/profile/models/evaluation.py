"""评价框架层数据模型。

结构为四级树：``EvaluationFramework``（框架）
→ ``Indicator``（指标）→ ``ObservationItem``（观测点）→ ``Rubric``（评分标准）。
最终与属性组合成 :class:`StudentEvaluationProfile`（学生实例）。
"""

from pydantic import BaseModel, Field


class Rubric(BaseModel):
    """评分标准的一个等级描述，用于统一不同教师的评价口径。"""

    level: int  # 等级序号，从 1 开始
    label: str  # 等级名称，如"未达成/初步/基本/熟练"
    description: str  # 该等级的行为描述
    evidence: str  # 判定该等级所需的观测证据要求


class ObservationItem(BaseModel):
    """观测点：指标下可观测的行为，是课堂数据采集的落点。"""

    key: str  # 观测点唯一键
    name: str  # 观测点名称，如"听到名字有反应"
    method: str  # 评价方式：quantitative / qualitative
    frequency: str  # 观测频率：per_lesson / weekly / phase
    evidence_sources: list[str] = Field(default_factory=list)  # 证据来源类型（见配置）
    rubrics: list[Rubric] = Field(default_factory=list)  # 评分标准等级


class Indicator(BaseModel):
    """指标：维度下的可评价能力项，如"听觉理解""社交互动"。"""

    key: str
    name: str
    dimension: str  # 所属评价维度
    observations: list[ObservationItem] = Field(default_factory=list)


class EvaluationFramework(BaseModel):
    """个性化评价框架：由类型与属性实例化生成。"""

    framework_id: str
    dimensions: list[str] = Field(default_factory=list)  # 参与评价的维度
    indicators: list[Indicator] = Field(default_factory=list)  # 指标清单
    weights: dict[str, float] = Field(default_factory=dict)  # 各维度权重（已归一化）
    dimension_indexes: dict[str, float] = Field(default_factory=dict)  # 各维度指数（0~1）
    prompt_template_key: str = ""


class StudentEvaluationProfile(BaseModel):
    """学生实例：属性（画像）+ 评价框架，是 profile 模块对外的最终契约。"""

    profile_id: str
    name: str
    attributes: "StudentAttributes"
    framework: EvaluationFramework
    created_at: str | None = None
    updated_at: str | None = None


# StudentAttributes 定义在 student.py，此处延迟导入以打破模块循环依赖
from kaleido.profile.models.student import StudentAttributes

# 字符串前向引用需要重新构建模型
StudentEvaluationProfile.model_rebuild()
