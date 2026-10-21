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


def test_long_content_is_not_judged():
    report = evaluate("这是一个非常非常长的句子" * 4, "courseware", {}, CONFIG)
    codes = _codes(report)
    assert "long_sentence" not in codes
    assert "too_long" not in codes
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


def test_avoid_visual_ref_flags_color_without_tactile():
    attributes = {
        "disabilities": ["visual"],
        "sensory_preference": "audio_first",
        "adaptation_constraints": {"avoid_visual_ref": True},
    }
    content = "# 颜色课 🎧\n\n- 红色 🍎\n- 黄色 🍌\n\n| 物体 | 颜色 |\n| --- | --- |\n| 苹果 | 红色 |"
    report = evaluate(content, "courseware", attributes, CONFIG)
    codes = _codes(report)
    assert "visual_conflict" in codes
    assert "color_no_tactile" in codes
    assert report["blocking"] is False


def test_avoid_visual_ref_allows_emoji():
    attributes = {
        "disabilities": ["visual"],
        "sensory_preference": "audio_first",
        "adaptation_constraints": {"avoid_visual_ref": True},
    }
    report = evaluate("朗读：红色苹果 🍎。摸一摸苹果。", "courseware", attributes, CONFIG)
    assert "visual_conflict" not in _codes(report)


def test_avoid_visual_ref_accepts_tactile_color_activity():
    attributes = {
        "disabilities": ["visual"],
        "sensory_preference": "audio_first",
        "adaptation_constraints": {"avoid_visual_ref": True},
    }
    content = "朗读：摸一摸苹果，感受光滑的皮。苹果是红色。"
    report = evaluate(content, "courseware", attributes, CONFIG)
    codes = _codes(report)
    assert "visual_conflict" not in codes
    assert "color_no_tactile" not in codes
