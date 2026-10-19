"""评价框架生成引擎测试：权重归一化、等级过滤与重度压缩。"""

import pytest

from kaleido.common.errors import ValidationError
from kaleido.profile.framework import FrameworkEngine


def test_weights_normalized():
    engine = FrameworkEngine.load()
    framework = engine.build("visual", "moderate", "primary_low", ["language"], "fw_test")
    assert set(framework.dimensions) == {
        "knowledge",
        "participation",
        "behavior",
        "rehabilitation",
    }
    # 权重归一化到 4 位小数，故使用 1e-3 容差
    assert abs(sum(framework.weights.values()) - 1.0) < 1e-3
    assert framework.weights["knowledge"] > framework.weights["participation"]


def test_cognitive_level_filters_indicators():
    engine = FrameworkEngine.load()
    framework = engine.build("visual", "moderate", "preschool", [], "fw_test")
    keys = {indicator.key for indicator in framework.indicators}
    assert "braille_literacy" not in keys


def test_severe_keeps_core_and_compresses():
    engine = FrameworkEngine.load()
    framework = engine.build("intellectual", "severe", "primary_low", [], "fw_test")
    keys = {indicator.key for indicator in framework.indicators}
    assert "basic_literacy" not in keys
    for indicator in framework.indicators:
        for obs in indicator.observations:
            assert obs.frequency == "per_lesson"
            assert len(obs.rubrics) == 3


def test_unknown_disability_raises():
    engine = FrameworkEngine.load()
    with pytest.raises(ValidationError):
        engine.build("unknown", "mild", "primary_low", [], "fw_test")
