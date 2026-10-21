"""facet 规则引擎：结构完整性检查与适配性风险提示。

不评价篇幅、字数、句长或是否使用 emoji；这些交给审查模型与教师判断。
"""

import re

from kaleido.forge.quality import analyze

_SUGGESTIONS = {
    "empty": "请重新生成或补充资源正文。",
    "unclosed_code": "补全 Markdown 代码块围栏。",
    "table_no_separator": "在表格表头下补充分隔行，保证表格可正常渲染。",
    "missing_读题稿": "为练习增加教师读题稿。",
    "missing_答案": "为练习补充参考答案。",
    "complex_terms": "用更口语化的词替换抽象术语，必要时配例子。",
    "sensory_missing": "补充与学生感官偏好匹配的线索（图像/语音/动手操作）。",
    "empty_alt_text": "为图像补充简洁的替代文本，方便视觉障碍学生理解。",
    "visual_conflict": "关键信息不要只靠表格或图片呈现，补充可朗读文字、触觉或听觉替代。",
    "color_no_tactile": "为颜色概念增加可触摸实物、纹理标签或温度/形状对比。",
}

_TACTILE_MARKERS = ("摸", "纹理", "实物", "温度", "形状", "触觉", "粗糙", "光滑")


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

    :returns: ``{ok, score, blocking, issues, stats}``；
        ``blocking`` 为真表示命中硬性错误，资源不应直接审核通过。
    """
    text = (content or "").strip()
    attributes = attributes or {}
    rules_config = config.get("rules") or {}
    hard_codes = set(config.get("hard_codes") or rules_config.get("hard_codes") or [])
    base = analyze(text, resource_type)
    issues: list[dict] = []

    for item in base["issues"]:
        code = str(item.get("code") or "")
        level = "error" if code in hard_codes else "warning"
        issues.append(_issue(code, level, str(item.get("message") or code)))

    if text:
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

        constraints = attributes.get("adaptation_constraints") or {}
        if constraints.get("avoid_visual_ref"):
            references: list[str] = []
            if re.search(r"^\s*\|", text, re.MULTILINE):
                references.append("表格")
            if "![" in text:
                references.append("图片")
            if references:
                issues.append(
                    _issue(
                        "visual_conflict",
                        "warning",
                        f"正文使用了{'、'.join(references)}；请确认关键信息同时有可朗读文字、触觉或听觉替代",
                    )
                )
            disabilities = attributes.get("disabilities") or []
            has_color_topic = any(
                word in text for word in ("颜色", "红色", "黄色", "蓝色", "绿色")
            )
            if (
                "visual" in disabilities
                and has_color_topic
                and not any(marker in text for marker in _TACTILE_MARKERS)
            ):
                issues.append(
                    _issue(
                        "color_no_tactile",
                        "warning",
                        "颜色概念缺少触觉、实物或多感官替代",
                    )
                )

    errors = sum(1 for item in issues if item["level"] == "error")
    warnings = sum(1 for item in issues if item["level"] == "warning")
    score = max(0, min(100, 100 - errors * 25 - warnings * 8))
    stats = {
        **base["stats"],
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
    }
