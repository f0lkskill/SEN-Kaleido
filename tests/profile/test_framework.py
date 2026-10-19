"""评价框架生成引擎测试：公共指标、权重归一化、维度指数与重度压缩。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import ValidationError
from kaleido.profile.framework import FrameworkEngine


def test_public_dimensions_and_weights_normalized():
    engine = FrameworkEngine.load()
    framework = engine.build(
        "visual", "moderate", "primary_3", "medium", ["language"], "fw_test"
    )
    # 当前阶段仅两个公共维度：课堂参与、练习质量
    assert set(framework.dimensions) == {"participation", "practice"}
    # 权重归一化到 4 位小数，故使用 1e-3 容差
    assert abs(sum(framework.weights.values()) - 1.0) < 1e-3
    # 康复目标 language 对 practice 加权，故 practice 权重应更高
    assert framework.weights["practice"] > framework.weights["participation"]


def test_dimension_indexes_within_range():
    engine = FrameworkEngine.load()
    framework = engine.build(
        "hearing", "mild", "primary_5", "fast", ["social"], "fw_test"
    )
    # 每个维度都有 0~1 的指数，保留两位小数
    assert set(framework.dimension_indexes) == {"participation", "practice"}
    for value in framework.dimension_indexes.values():
        assert 0.0 <= value <= 1.0
        assert round(value, 2) == value
    # 轻度 + 高认知 + 快节奏，指数应偏高
    assert framework.dimension_indexes["participation"] > 0.6


def test_severe_lowers_indexes():
    engine = FrameworkEngine.load()
    mild = engine.build("visual", "mild", "primary_5", "fast", [], "fw_test")
    severe = engine.build("visual", "severe", "preschool", "slow", [], "fw_test")
    assert mild.dimension_indexes["practice"] > severe.dimension_indexes["practice"]


def test_public_indicators_present_for_all():
    engine = FrameworkEngine.load()
    framework = engine.build("visual", "moderate", "preschool", "slow", [], "fw_test")
    keys = {indicator.key for indicator in framework.indicators}
    # 公共指标不随障碍类型/认知等级裁剪
    assert keys == {"class_participation", "practice_quality"}


def test_severe_compresses_and_bumps_frequency():
    engine = FrameworkEngine.load()
    framework = engine.build(
        "intellectual", "severe", "primary_3", "slow", [], "fw_test"
    )
    for indicator in framework.indicators:
        for obs in indicator.observations:
            assert obs.frequency == "per_lesson"
            assert len(obs.rubrics) == 3


def test_unknown_cognitive_level_raises():
    engine = FrameworkEngine.load()
    with pytest.raises(ValidationError):
        engine.build("visual", "mild", "unknown", "medium", [], "fw_test")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
