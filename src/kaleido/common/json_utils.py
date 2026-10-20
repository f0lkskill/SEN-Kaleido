"""宽松 JSON 解析：从模型输出中提取完整或被截断的 JSON 对象。

模型可能返回 Markdown 代码块、前后说明文字、多个 JSON 对象，或在
``max_tokens`` 截止时留下未闭合的字符串/数组/对象。这里先扫描平衡的
JSON 对象，再对最后一个未闭合对象做最小修复，避免整次结果作废。
"""

import json
import re
from typing import Any


def _balanced_objects(text: str) -> list[str]:
    """扫描文本，返回所有括号平衡的顶层 JSON 对象。"""
    objects: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                objects.append(text[start : index + 1])
                start = -1
    if start >= 0:
        # 结尾未闭合：把剩余部分交给修复逻辑
        objects.append(text[start:])
    return objects


def _repair(text: str) -> str:
    """对截断/含尾逗号的 JSON 做最小修复。"""
    repaired = re.sub(r",\s*([}\]])", r"\1", text.strip())
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in repaired:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    if in_string:
        repaired += '"'
    repaired += "".join(reversed(stack))
    return re.sub(r",\s*([}\]])", r"\1", repaired)


def _try_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _from_object(data: Any) -> dict | None:
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
    return None


def loads_json_object(
    content: str,
    preferred_keys: tuple[str, ...] = (),
) -> dict | None:
    """从模型输出中提取 JSON 对象；失败返回 ``None``。

    :param content: 模型原始输出
    :param preferred_keys: 优先选择的字段（用于在多个 JSON 对象中选主结果）
    """
    text = (content or "").strip()
    if not text:
        return None
    # 去掉代码块围栏，保留围栏内内容
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    candidates = _balanced_objects(text)
    if not candidates:
        return None

    parsed: list[tuple[int, dict]] = []
    for index, candidate in enumerate(candidates):
        data = _try_loads(candidate)
        if data is None:
            data = _try_loads(_repair(candidate))
        obj = _from_object(data)
        if obj is None:
            continue
        score = sum(1 for key in preferred_keys if key in obj)
        parsed.append((score * 1000 + len(obj), obj))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0], reverse=True)
    return parsed[0][1]
