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
from kaleido.forge.llm_client import DeepSeekClient, StubClient, create_client


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


def test_create_client_provider_stub():
    assert isinstance(create_client({"provider": "stub"}), StubClient)
    assert isinstance(create_client({"provider": "deepseek"}), DeepSeekClient)


def test_missing_api_key(monkeypatch):
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

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
