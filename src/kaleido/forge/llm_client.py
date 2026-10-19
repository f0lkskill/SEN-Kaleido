"""云端大模型客户端。

直接使用 ``requests`` 调用 OpenAI 兼容接口（DeepSeek ``deepseek-flash``），
不引入 LangChain/LlamaIndex 等重依赖。通过 :class:`LLMClient` 抽象，
测试可注入 :class:`StubClient`，无需联网。
"""

import os
from typing import Protocol

import requests
from pydantic import BaseModel, Field

from kaleido.common.errors import ConfigError, UpstreamError


class LLMResult(BaseModel):
    """一次模型调用的结果。"""

    content: str
    model: str = ""
    usage: dict = Field(default_factory=dict)


class LLMClient(Protocol):
    """模型客户端协议。"""

    def complete(self, messages: list[dict[str, str]], **overrides) -> LLMResult:
        """输入对话消息，返回补全结果。"""
        ...


class DeepSeekClient:
    """DeepSeek OpenAI 兼容接口客户端。"""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.model = config.get("model", "deepseek-flash")
        self.timeout = float(config.get("timeout", 60))
        self.retries = int(config.get("retries", 2))
        self.api_key_env = config.get("api_key_env", "DEEPSEEK_API_KEY")

    def _api_key(self) -> str:
        """从环境变量读取密钥（密钥只存于基站，不下发客户端）。"""
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ConfigError(f"未设置环境变量 {self.api_key_env}")
        return key

    def complete(self, messages: list[dict[str, str]], **overrides) -> LLMResult:
        """调用 ``/chat/completions``，失败时按配置重试。"""
        payload = {
            "model": overrides.get("model", self.model),
            "messages": messages,
            "temperature": overrides.get("temperature", self.config.get("temperature", 0.7)),
            "max_tokens": overrides.get("max_tokens", self.config.get("max_tokens", 2048)),
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = requests.post(
                    url, json=payload, headers=headers, timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                return LLMResult(
                    content=data["choices"][0]["message"]["content"],
                    model=data.get("model", self.model),
                    usage=data.get("usage", {}),
                )
            except (requests.RequestException, KeyError, IndexError) as exc:
                last_error = exc
        raise UpstreamError(f"云端模型调用失败: {last_error}")


class StubClient:
    """离线桩客户端：返回固定内容并记录调用，供测试与本地联调使用。"""

    def __init__(self, content: str = "[stub] 生成内容", usage: dict | None = None):
        self.content = content
        self.usage = usage or {"total_tokens": 0}
        self.calls: list[dict] = []

    def complete(self, messages: list[dict[str, str]], **overrides) -> LLMResult:
        self.calls.append({"messages": messages, **overrides})
        return LLMResult(content=self.content, model="stub", usage=self.usage)


def create_client(config: dict) -> LLMClient:
    """按配置创建客户端；``provider=stub`` 时返回离线桩。"""
    if config.get("provider") == "stub":
        return StubClient()
    return DeepSeekClient(config)
