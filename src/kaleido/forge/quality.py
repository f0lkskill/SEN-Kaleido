"""生成质量检查：Markdown 结构完整性与资源类型必备部分。

这里只做结构性检查，不评价篇幅、字数、句长或表达风格；
内容适配性交给质量审查模型与教师判断。
"""

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


def analyze(content: str, resource_type: str) -> dict:
    """检查生成内容的结构完整性。

    :returns: ``{ok, issues, stats}``；``issues`` 每项含 ``code`` 与
        ``message``，便于前端按类型展示。
    """
    text = (content or "").strip()
    issues: list[dict] = []

    if not text:
        issues.append({"code": "empty", "message": "生成内容为空"})

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

    return {
        "ok": not issues,
        "issues": issues,
        "stats": {},
    }
