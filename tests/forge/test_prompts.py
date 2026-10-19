"""Prompt 模板测试：渲染占位、约束注入与缺失模板报错。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import ConfigError
from kaleido.forge.prompts import load_template, render

MAPPING = {
    "severity": "moderate",
    "cognitive_level": "primary_3",
    "sensory_preference": "audio_first",
    "learning_pace": "slow",
    "constraints": '{"format": "voice_first"}',
    "resource_type": "分层知识点课件",
    "topic": "认识四季",
    "extra": "无",
}


@pytest.mark.parametrize(
    "key", ["visual_layer", "hearing_layer", "intellectual_layer", "autism_layer"]
)
def test_render_all_layers(key):
    text = render(key, MAPPING)
    assert "认识四季" in text
    assert "分层知识点课件" in text
    assert "voice_first" in text
    assert "moderate" in text


def test_missing_placeholder_renders_empty():
    text = render("visual_layer", {"topic": "x"})
    assert "x" in text


def test_missing_template_raises():
    with pytest.raises(ConfigError):
        load_template("no_such_layer")

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
