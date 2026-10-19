"""评价框架生成引擎。

当前阶段所有学生共用公共指标（上课参与度、练习完成质量），规则如下：
- 指标来自配置 ``public_indicators``，不随障碍类型或认知等级裁剪；
- 按康复目标加权：对相关评价维度增加权重后整体归一化；
- ``severe`` 时提升观测频率并压缩评分标准等级数，降低评价负担。
"""

from kaleido.common.errors import ValidationError
from kaleido.profile.config_loader import load_config, load_rubric
from kaleido.profile.models.evaluation import (
    EvaluationFramework,
    Indicator,
    ObservationItem,
    Rubric,
)

# 重度障碍时评分标准保留的等级数
SEVERE_MAX_RUBRIC_LEVELS = 3


class FrameworkEngine:
    """评价框架生成引擎。"""

    def __init__(self, config: dict, level_order: list[str]):
        self.config = config  # evaluation_frameworks.yaml 内容
        self.level_order = level_order  # 认知等级顺序，用于比较高低

    @classmethod
    def load(cls) -> "FrameworkEngine":
        """从配置文件加载引擎。"""
        config = load_config("evaluation_frameworks")
        level_order = load_config("attributes").get("cognitive_level_order", [])
        return cls(config, level_order)

    def build(
        self,
        primary_disability: str,
        severity: str,
        cognitive_level: str,
        rehab_goals: list[str],
        framework_id: str,
    ) -> EvaluationFramework:
        """生成评价框架（当前阶段为公共框架）。

        参数 ``primary_disability`` 仅用于推导 Prompt 模板键；
        指标统一取自 ``public_indicators``，所有学生一致。
        """
        if cognitive_level not in self.level_order:
            raise ValidationError(f"未知认知等级: {cognitive_level}")

        indicators = [
            self._build_indicator(item, severity)
            for item in self.config.get("public_indicators", [])
        ]
        dimensions = list(self.config.get("dimensions", {}).keys())
        weights = self._compute_weights(
            self.config.get("base_weights", {}),
            self.config.get("goal_weight_bonus", {}),
            dimensions,
            rehab_goals,
        )
        return EvaluationFramework(
            framework_id=framework_id,
            dimensions=dimensions,
            indicators=indicators,
            weights=weights,
            prompt_template_key=f"{primary_disability}_layer",
        )

    def _build_indicator(self, item: dict, severity: str) -> Indicator:
        """构建单个指标及其观测点与评分标准。"""
        observations: list[ObservationItem] = []
        for obs in item.get("observations", []):
            rubric_config = load_rubric(obs["rubric"])
            levels = list(rubric_config.get("levels", []))
            # 重度障碍压缩评分等级，降低教师评价负担
            if severity == "severe":
                levels = levels[:SEVERE_MAX_RUBRIC_LEVELS]
            # 重度障碍提升观测频率到每课
            frequency = "per_lesson" if severity == "severe" else obs.get("frequency", "weekly")
            observations.append(
                ObservationItem(
                    key=obs["key"],
                    name=obs["name"],
                    method=obs.get("method", "quantitative"),
                    frequency=frequency,
                    evidence_sources=list(obs.get("evidence_sources", [])),
                    rubrics=[Rubric(**level) for level in levels],
                )
            )
        return Indicator(
            key=item["key"],
            name=item["name"],
            dimension=item["dimension"],
            observations=observations,
        )

    def _compute_weights(
        self,
        base: dict,
        bonus_map: dict,
        dimensions: list[str],
        rehab_goals: list[str],
    ) -> dict[str, float]:
        """计算并归一化各维度权重。"""
        weights = {dim: float(base.get(dim, 0.0)) for dim in dimensions}
        # 依据康复目标给相关维度加权
        for goal in rehab_goals:
            for dim, delta in bonus_map.get(goal, {}).items():
                if dim in weights:
                    weights[dim] += float(delta)
        total = sum(weights.values())
        if total <= 0:
            return weights
        # 归一化，保证权重之和为 1
        return {dim: round(value / total, 4) for dim, value in weights.items()}
