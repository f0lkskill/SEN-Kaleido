from kaleido.common.json_utils import loads_json_object


def test_parse_fenced_json_with_prose():
    content = '下面是结果：\n```json\n{"summary": "不错", "scores": {"a": 90}}\n```\n请查收。'
    data = loads_json_object(content, preferred_keys=("summary", "scores"))
    assert data == {"summary": "不错", "scores": {"a": 90}}


def test_parse_truncated_json():
    content = (
        '{"summary": "截断前的内容", "scores": {"fit": 88}, '
        '"issues": ["缺少步骤图"], "prompts": ["补充步骤图'
    )
    data = loads_json_object(content, preferred_keys=("summary", "scores"))
    assert data is not None
    assert data["summary"] == "截断前的内容"
    assert data["scores"] == {"fit": 88}
    assert data["prompts"] == ["补充步骤图"]


def test_parse_trailing_commas():
    content = '{"summary": "ok", "issues": ["a",],}'
    data = loads_json_object(content, preferred_keys=("summary",))
    assert data == {"summary": "ok", "issues": ["a"]}


def test_choose_object_with_preferred_keys():
    content = '{"note": "前言"} 正式结果：{"summary": "主结果", "scores": {}}'
    data = loads_json_object(content, preferred_keys=("summary", "scores"))
    assert data == {"summary": "主结果", "scores": {}}


def test_braces_and_quotes_inside_strings():
    content = '{"summary": "包含 } 和 { 以及 \\"引号\\"", "scores": {}}'
    data = loads_json_object(content, preferred_keys=("summary",))
    assert data is not None
    assert data["summary"] == '包含 } 和 { 以及 "引号"'


def test_invalid_text_returns_none():
    assert loads_json_object("模型只返回了一段说明") is None
