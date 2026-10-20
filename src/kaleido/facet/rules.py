"""facet 规则引擎：在 forge 轻量检查之上补充适配性硬规则与软警告。"""

import re

from kaleido.forge.quality import analyze

_SUGGESTIONS = {
    "empty": "请重新生成或补充资源正文。",
    "unclosed_code": "补全 Markdown 代码块围栏。",
    "table_no_separator": "在表格表头下补充分隔行，保证表格可正常渲染。",
    "long_sentence": "把长句拆成短句，每句只表达一个信息点。",
    "missing_读题稿": "为练习增加教师读题稿。",
    "missing_答案": "为练习补充参考答案。",
    "too_long": "压缩正文或拆分为多个课时。",
    "complex_terms": "用更口语化的词替换抽象术语，必要时配例子。",
    "sensory_missing": "补充与学生感官偏好匹配的线索（图像/语音/动手操作）。",
    "empty_alt_text": "为图像补充简洁的替代文本，方便视觉障碍学生理解。",
}


def _issue(code: str, level: str, message: str) -> dict:
    """构造统一格式的规则命中项。"""
    return {
        "code": code,
        "level": level,
        "message": message,
        "suggestion": _SUGGESTIONS.get(code, ""),
    }


def evaluate(
    content: str,
    resource_type: str,
    attributes: dict | None,
    config: dict,
) -> dict:
    """执行规则校验。

    :returns: ``{ok, score, blocking, issues, stats, long_sentences}``；
        ``blocking`` 为真表示命中硬性错误，资源不应直接审核通过。
    """
    text = (content or "").strip()
    attributes = attributes or {}
    rules_config = config.get("rules") or {}
    max_sentence = (config.get("max_sentence_chars") or {}).get(resource_type, 16)
    hard_codes = set(config.get("hard_codes") or rules_config.get("hard_codes") or [])
    base = analyze(text, resource_type, max_sentence_len=max_sentence)
    issues: list[dict] = []

    for item in base["issues"]:
        code = str(item.get("code") or "")
        level = "error" if code in hard_codes else "warning"
        issues.append(_issue(code, level, str(item.get("message") or code)))

    if text:
        max_chars = (config.get("max_characters") or {}).get(resource_type)
        if max_chars and len(text) > int(max_chars):
            issues.append(
                _issue(
                    "too_long",
                    "warning",
                    f"正文 {len(text)} 字，超过该资源类型的建议上限 {max_chars} 字",
                )
            )

        terms = [str(term) for term in config.get("complex_terms") or [] if str(term)]
        term_hits = [term for term in terms if term in text]
        term_count = sum(text.count(term) for term in term_hits)
        limit = int(config.get("complex_term_limit", 8))
        if term_count > limit:
            preview = "、".join(term_hits[:6])
            issues.append(
                _issue(
                    "complex_terms",
                    "warning",
                    f"出现 {term_count} 次抽象/书面化术语（{preview}），可能增加理解负担",
                )
            )

        preference = str(attributes.get("sensory_preference") or "")
        markers = (config.get("sensory_markers") or {}).get(preference) or []
        if markers and not any(str(marker) in text for marker in markers):
            issues.append(
                _issue(
                    "sensory_missing",
                    "warning",
                    "正文未发现与该学生感官偏好匹配的表征线索",
                )
            )
        if preference == "visual_first" and re.search(r"!\[\s*\]\(", text):
            issues.append(
                _issue("empty_alt_text", "warning", "图像缺少替代文本（alt）")
            )

    errors = sum(1 for item in issues if item["level"] == "error")
    warnings = sum(1 for item in issues if item["level"] == "warning")
    score = max(0, min(100, 100 - errors * 25 - warnings * 8))
    stats = {
        **base["stats"],
        "characters": len(text),
        "errors": errors,
        "warnings": warnings,
        "sensory_preference": attributes.get("sensory_preference", ""),
    }
    return {
        "ok": errors == 0,
        "score": score,
        "blocking": errors > 0,
        "issues": issues,
        "stats": stats,
        "long_sentences": base["long_sentences"],
    }
