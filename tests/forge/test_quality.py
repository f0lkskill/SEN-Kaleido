"""生成质量检查测试。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.forge.quality import analyze


def test_clean_content_passes():
    report = analyze("# 标题\n\n- 短句一。\n- 短句二。", "courseware")
    assert report["ok"] is True
    assert report["issues"] == []


def test_empty_content_flagged():
    report = analyze("   ", "courseware")
    assert report["ok"] is False
    assert any(issue["code"] == "empty" for issue in report["issues"])


def test_length_is_not_judged():
    long_text = "这是一个非常非常长的句子" * 4
    report = analyze(long_text, "courseware")
    assert report["ok"] is True
    assert all(issue["code"] != "long_sentence" for issue in report["issues"])
    assert "max_length" not in report["stats"]


def test_unclosed_code_block_flagged():
    report = analyze("```\n代码", "courseware")
    assert any(issue["code"] == "unclosed_code" for issue in report["issues"])


def test_table_without_separator_flagged():
    report = analyze("| 分层 | 说明 |\n| 基础 | 第一层 |", "courseware")
    assert any(issue["code"] == "table_no_separator" for issue in report["issues"])


def test_exercise_missing_parts_flagged():
    report = analyze("1. 一加一等于几？", "exercise")
    codes = {issue["code"] for issue in report["issues"]}
    assert "missing_读题稿" in codes
    assert "missing_答案" in codes
