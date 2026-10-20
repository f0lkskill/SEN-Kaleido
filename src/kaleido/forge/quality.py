"""生成质量检查：句子长度、Markdown 结构与资源类型必备部分。

模型输出是自由文本，难以保证完全符合规范；这里做轻量静态检查，
把问题以结构化形式回传前端提示教师，而不是静默接受低质量内容。
"""

import re

# 不同资源类型允许的单句最大字数
_SENTENCE_LIMITS = {
    "exercise": 12,
    "courseware": 16,
    "rehabilitation": 16,
    "interaction": 14,
    "iep": 20,
}

# 句子分隔：中英文句末标点与换行
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")

# 练习题库必须具备的部分（关键词）
_EXERCISE_PARTS = ("读题稿", "答案")


def _is_table_separator(line: str) -> bool:
    """判断是否为 Markdown 表格分隔行（如 ``| --- | --- |``）。"""
    cells = line.strip().strip("|").split("|")
    if not cells:
        return False
    for cell in cells:
        stripped = cell.strip().replace(" ", "")
        if not stripped or not set(stripped) <= {"-", ":"} or "-" not in stripped:
            return False
    return True


def _sentence_text(text: str) -> str:
    """剔除图片行与表格行，避免 Markdown 语法被误判为长句。"""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") or (
            stripped.startswith("![") and stripped.endswith(")")
        ):
            continue
        lines.append(line)
    return "\n".join(lines)


def analyze(content: str, resource_type: str, max_sentence_len: int | None = None) -> dict:
    """检查生成内容。

    :returns: ``{ok, issues, stats, long_sentences}``；``issues`` 每项含
        ``code`` 与 ``message``，便于前端按类型展示。
    """
    text = (content or "").strip()
    limit = max_sentence_len or _SENTENCE_LIMITS.get(resource_type, 16)
    issues: list[dict] = []

    sentences = [
        part.strip()
        for part in _SENTENCE_SPLIT.split(_sentence_text(text))
        if part.strip()
    ]
    long_sentences = [
        {"length": len(sentence), "text": sentence[:40]}
        for sentence in sentences
        if len(sentence) > limit
    ]

    if not text:
        issues.append({"code": "empty", "message": "生成内容为空"})
    if long_sentences:
        issues.append(
            {
                "code": "long_sentence",
                "message": f"有 {len(long_sentences)} 句超过 {limit} 字，建议拆分",
            }
        )

    if text.count("```") % 2 != 0:
        issues.append({"code": "unclosed_code", "message": "代码块围栏未闭合"})

    # 连续以 | 开头的行若没有分隔行，Markdown 表格将无法正确渲染
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.strip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2 and not any(_is_table_separator(item) for item in block):
            issues.append(
                {
                    "code": "table_no_separator",
                    "message": "表格缺少分隔行（如 | --- | --- |）",
                }
            )
        block = []

    # 练习题库应包含读题稿与答案
    if resource_type == "exercise" and text:
        for part in _EXERCISE_PARTS:
            if part not in text:
                issues.append(
                    {"code": f"missing_{part}", "message": f"练习题库缺少「{part}」部分"}
                )

    stats = {
        "sentences": len(sentences),
        "long_sentences": len(long_sentences),
        "max_length": max((len(sentence) for sentence in sentences), default=0),
        "characters": len(text),
    }
    return {
        "ok": not issues,
        "issues": issues,
        "stats": stats,
        "long_sentences": long_sentences,
    }
