"""模型客户端测试：桩、配置、请求构造、重试与错误映射。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest
import requests

from kaleido.common.errors import ConfigError, UpstreamError
from kaleido.forge import llm_client
from kaleido.forge.llm_client import (
    DeepSeekClient,
    StubClient,
    create_client,
    stream_complete,
)


class FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


def test_stub_client_records_calls():
    client = StubClient(content="hello", usage={"total_tokens": 3})
    result = client.complete([{"role": "user", "content": "x"}])
    assert result.content == "hello"
    assert client.calls[0]["messages"][0]["content"] == "x"


def test_create_client_provider_stub(monkeypatch):
    # 屏蔽 .env 加载，保证测试环境隔离
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    assert isinstance(create_client({"provider": "stub"}), StubClient)
    assert isinstance(create_client({"provider": "deepseek"}), DeepSeekClient)


def test_create_client_falls_back_without_key(monkeypatch):
    # 无密钥时自动回退离线桩，避免启动即失败
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("NOKEY", raising=False)
    assert isinstance(
        create_client({"provider": "deepseek", "api_key_env": "NOKEY"}), StubClient
    )


def test_create_client_does_not_log_misplaced_secret(monkeypatch, caplog):
    # 密钥误填到 api_key_env 时只提示，不把密钥写进日志
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("sk-secret", raising=False)
    with caplog.at_level("WARNING"):
        client = create_client({"provider": "deepseek", "api_key_env": "sk-secret"})
    assert isinstance(client, StubClient)
    assert "sk-secret" not in caplog.text


def test_missing_key_error_does_not_leak_secret(monkeypatch):
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("sk-secret", raising=False)
    client = DeepSeekClient({"api_key_env": "sk-secret"})
    with pytest.raises(ConfigError) as exc:
        client.complete([{"role": "user", "content": "x"}])
    assert "sk-secret" not in str(exc.value)


def test_api_key_from_config(monkeypatch):
    # 配置里的 api_key 优先于环境变量
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    client = DeepSeekClient({"api_key": "from-config", "api_key_env": "NOKEY"})
    assert client.has_credentials()


def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("TEST_KEY", raising=False)
    client = DeepSeekClient({"api_key_env": "TEST_KEY"})
    with pytest.raises(ConfigError):
        client.complete([{"role": "user", "content": "x"}])


def test_deepseek_request_and_result(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse(
            {
                "model": "deepseek-flash",
                "choices": [{"message": {"content": "生成结果"}}],
                "usage": {"total_tokens": 10},
            }
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = DeepSeekClient(
        {"api_key_env": "TEST_KEY", "base_url": "https://api.deepseek.com", "model": "m"}
    )
    result = client.complete([{"role": "user", "content": "x"}])

    assert result.content == "生成结果"
    assert result.usage == {"total_tokens": 10}
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"]["stream"] is False
    assert "max_tokens" not in captured["json"]


def test_max_tokens_override_is_sent(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured.update(json=json)
        return FakeResponse(
            {
                "model": "deepseek-flash",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            }
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = DeepSeekClient(
        {"api_key_env": "TEST_KEY", "max_tokens": None, "retries": 0}
    )
    client.complete([{"role": "user", "content": "x"}], max_tokens=123)
    assert captured["json"]["max_tokens"] == 123


def test_deepseek_retries_then_upstream_error(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    calls = {"n": 0}

    def failing_post(*args, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(llm_client.requests, "post", failing_post)
    client = DeepSeekClient({"api_key_env": "TEST_KEY", "retries": 1})
    with pytest.raises(UpstreamError):
        client.complete([{"role": "user", "content": "x"}])
    assert calls["n"] == 2

def test_deepseek_empty_content_raises(monkeypatch):
    # 正文为空（推理占满额度/输出截断）时应报错，而不是静默返回空内容
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("TEST_KEY", "secret")

    def fake_post(*args, **kwargs):
        return FakeResponse(
            {
                "model": "m",
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "思路…"},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"total_tokens": 5},
            }
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = DeepSeekClient({"api_key_env": "TEST_KEY", "retries": 0})
    with pytest.raises(UpstreamError):
        client.complete([{"role": "user", "content": "x"}])


class FakeStreamResponse:
    """模拟流式响应：按行产出 SSE 数据。"""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = False):
        return iter(self._lines)


class _StreamingClient:
    """最小流式客户端，用于验证通用流式封装。"""

    model = "stream-model"

    def complete(self, messages, **overrides):  # pragma: no cover
        raise AssertionError("流式路径不应调用 complete")

    def stream(self, messages, **overrides):
        yield {"type": "reasoning", "text": "想"}
        yield {"type": "content", "text": "正文"}


def test_stream_complete_forwards_events():
    events: list[dict] = []
    result = stream_complete(
        _StreamingClient(),
        [{"role": "user", "content": "x"}],
        on_event=events.append,
    )
    assert result.content == "正文"
    assert result.model == "stream-model"
    assert events == [
        {"type": "reasoning", "text": "想"},
        {"type": "content", "text": "正文"},
    ]


def test_stream_complete_falls_back_to_complete():
    events: list[dict] = []
    result = stream_complete(
        StubClient(content="一次性输出"),
        [{"role": "user", "content": "x"}],
        on_event=events.append,
    )
    assert result.content == "一次性输出"
    assert events == [{"type": "content", "text": "一次性输出"}]


def test_deepseek_stream_parses_deltas(monkeypatch):
    monkeypatch.setattr(llm_client, "load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("TEST_KEY", "secret")
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"想"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"正"}}]}',
        'data: {"choices":[{"delta":{"content":"文"}}]}',
        "data: [DONE]",
    ]

    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeStreamResponse(lines))
    client = DeepSeekClient({"api_key_env": "TEST_KEY", "model": "m"})
    events = list(client.stream([{"role": "user", "content": "x"}]))
    assert {"type": "reasoning", "text": "想"} in events
    assert events[-2:] == [
        {"type": "content", "text": "正"},
        {"type": "content", "text": "文"},
    ]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
