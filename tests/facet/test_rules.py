"""facet 规则引擎测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.common.config import load_yaml
from kaleido.facet.rules import evaluate

CONFIG = load_yaml("facet", "facet")


def _codes(report):
    return {issue["code"] for issue in report["issues"]}


def test_clean_visual_content_passes():
    content = "# 认识四季\n\n![四季图](sample.png)\n\n| 季节 | 特点 |\n| --- | --- |\n| 春 | 花开。 |"
    report = evaluate(content, "courseware", {"sensory_preference": "visual_first"}, CONFIG)
    assert report["ok"] is True
    assert report["blocking"] is False
    assert report["score"] == 100


def test_empty_content_blocks():
    report = evaluate("   ", "courseware", {}, CONFIG)
    assert report["blocking"] is True
    assert "empty" in _codes(report)


def test_long_sentence_is_warning_only():
    report = evaluate("这是一个非常非常长的句子" * 4, "courseware", {}, CONFIG)
    assert "long_sentence" in _codes(report)
    assert report["blocking"] is False


def test_missing_exercise_parts_blocks():
    report = evaluate("1. 一加一等于几？", "exercise", {}, CONFIG)
    codes = _codes(report)
    assert "missing_读题稿" in codes
    assert "missing_答案" in codes
    assert report["blocking"] is True


def test_sensory_marker_missing_warns():
    report = evaluate("今天我们学习四季。春天花开。", "courseware", {"sensory_preference": "audio_first"}, CONFIG)
    assert "sensory_missing" in _codes(report)
    assert report["blocking"] is False


def test_empty_alt_text_warns():
    content = "![ ](sample.png)\n\n朗读：春天来了。"
    report = evaluate(content, "courseware", {"sensory_preference": "visual_first"}, CONFIG)
    assert "empty_alt_text" in _codes(report)


def test_complex_terms_warn():
    content = "综上所述，" * 9 + "朗读：春天来了。"
    report = evaluate(content, "courseware", {"sensory_preference": "audio_first"}, CONFIG)
    assert "complex_terms" in _codes(report)
