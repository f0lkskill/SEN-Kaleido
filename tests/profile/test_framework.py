"""评价框架生成引擎测试：权重归一化、等级过滤与重度压缩。"""

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

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
