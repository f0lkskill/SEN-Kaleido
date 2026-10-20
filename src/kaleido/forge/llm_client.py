"""云端大模型客户端。

直接使用 ``requests`` 调用 OpenAI 兼容接口（DeepSeek ``deepseek-flash``），
不引入 LangChain/LlamaIndex 等重依赖。通过 :class:`LLMClient` 抽象，
测试可注入 :class:`StubClient`，无需联网。
"""

import json
import logging
import os
from collections.abc import Iterator
from typing import Any, Protocol

import requests
from pydantic import BaseModel, Field

from kaleido.common.config import load_env_file
from kaleido.common.errors import ConfigError, UpstreamError

logger = logging.getLogger("kaleido.forge")


class LLMResult(BaseModel):
    """一次模型调用的结果。"""

    content: str
    model: str = ""
    usage: dict = Field(default_factory=dict)


class LLMClient(Protocol):
    """模型客户端协议。"""

    def complete(self, messages: list[dict[str, Any]], **overrides) -> LLMResult:
        """输入对话消息，返回补全结果；消息内容支持文本或多模态内容块。"""
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

    def _resolve_api_key(self) -> str:
        """解析密钥：配置 ``api_key`` 优先，其次环境变量，最后尝试加载 ``.env``。"""
        key = str(self.config.get("api_key") or "").strip()
        if key:
            return key
        key = os.environ.get(self.api_key_env, "").strip()
        if key:
            return key
        # 现场尝试从项目根 .env 载入（不入库的敏感项存放处）
        load_env_file()
        return os.environ.get(self.api_key_env, "").strip()

    def has_credentials(self) -> bool:
        """是否已具备可用密钥。"""
        return bool(self._resolve_api_key())

    def _api_key(self) -> str:
        """读取密钥（密钥只存于基站，不下发客户端）。"""
        key = self._resolve_api_key()
        if not key:
            raise ConfigError(
                "未设置模型密钥：请在 .env 配置 DEEPSEEK_API_KEY，"
                "或检查 llm.api_key_env 是否为环境变量名"
            )
        return key

    def complete(self, messages: list[dict[str, Any]], **overrides) -> LLMResult:
        """调用 ``/chat/completions``，失败时按配置重试。"""
        payload = {
            "model": overrides.get("model", self.model),
            "messages": messages,
            "temperature": overrides.get("temperature", self.config.get("temperature", 0.7)),
            "max_tokens": overrides.get("max_tokens", self.config.get("max_tokens", 2048)),
            "stream": False,
        }
        if overrides.get("response_format"):
            payload["response_format"] = overrides["response_format"]
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        logger.info("模型请求: model=%s max_tokens=%s", payload["model"], payload["max_tokens"])
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = requests.post(
                    url, json=payload, headers=headers, timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                message = choice.get("message", {}) or {}
                content = (message.get("content") or "").strip()
                reasoning = (message.get("reasoning_content") or "").strip()
                finish = choice.get("finish_reason", "")
                usage = data.get("usage", {})
                logger.info(
                    "模型返回: model=%s finish=%s content_len=%d reasoning_len=%d tokens=%s",
                    data.get("model", self.model),
                    finish,
                    len(content),
                    len(reasoning),
                    usage.get("total_tokens"),
                )
                # 空正文：多为推理内容占满额度或输出被截断，视为可重试的失败
                if not content:
                    if reasoning:
                        detail = "模型只返回了推理内容（reasoning_content），正文为空"
                    elif finish == "length":
                        detail = "输出达到 max_tokens 上限，正文被截断"
                    else:
                        detail = "模型返回了空内容"
                    last_error = UpstreamError(
                        f"{detail}（finish_reason={finish or '未知'}）；"
                        "请提高 configs/forge/forge.yaml 的 max_tokens，或改用非推理模型"
                    )
                    logger.warning("生成异常: %s", last_error)
                    continue
                return LLMResult(content=content, model=data.get("model", self.model), usage=usage)
            except requests.HTTPError as exc:
                # 保留响应体，便于定位模型名/参数/额度等接口级错误
                resp = exc.response
                if resp is not None and resp.status_code == 402:
                    last_error = UpstreamError(
                        "模型账户余额不足（402 Payment Required），"
                        "请充值或切换离线桩客户端（SEN_KALEIDO_LLM_PROVIDER=stub）"
                    )
                    logger.error("模型账户余额不足: %s", exc)
                    break
                body = resp.text[:500] if resp is not None else ""
                logger.error("模型接口返回错误: %s %s", exc, body)
                last_error = UpstreamError(f"接口错误 {exc}：{body}")
            except (requests.RequestException, KeyError, IndexError) as exc:
                logger.error("模型调用异常: %s", exc)
                last_error = exc
        raise UpstreamError(f"云端模型调用失败: {last_error}")

    def stream(self, messages: list[dict[str, str]], **overrides) -> Iterator[dict]:
        """流式调用 ``/chat/completions``，逐块产出增量。

        产出形如 ``{"type": "reasoning"|"content", "text": str}`` 的事件：
        推理模型会先持续产出 ``reasoning``（思考过程），随后产出 ``content``（正文）。
        """
        payload = {
            "model": overrides.get("model", self.model),
            "messages": messages,
            "temperature": overrides.get("temperature", self.config.get("temperature", 0.7)),
            "max_tokens": overrides.get("max_tokens", self.config.get("max_tokens", 2048)),
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=(10, self.timeout),
            stream=True,
        )
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            # iter_lines 在不同版本可能返回 bytes 或 str，这里统一转为 str
            line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content")
            content = delta.get("content")
            if reasoning:
                yield {"type": "reasoning", "text": reasoning}
            if content:
                yield {"type": "content", "text": content}


class StubClient:
    """离线桩客户端：返回固定内容并记录调用，供测试与本地联调使用。"""

    def __init__(self, content: str = "[stub] 生成内容", usage: dict | None = None):
        self.content = content
        self.usage = usage or {"total_tokens": 0}
        self.calls: list[dict] = []

    def complete(self, messages: list[dict[str, Any]], **overrides) -> LLMResult:
        self.calls.append({"messages": messages, **overrides})
        return LLMResult(content=self.content, model="stub", usage=self.usage)


def create_client(config: dict) -> LLMClient:
    """按配置创建客户端。

    - ``provider=stub``（或环境变量 ``SEN_KALEIDO_LLM_PROVIDER=stub``）时返回离线桩；
    - 否则创建真实客户端，但**若未检测到密钥则回退离线桩**，
      保证无密钥部署也能正常体验前端，不会启动即失败。
    """
    provider = os.environ.get("SEN_KALEIDO_LLM_PROVIDER") or config.get("provider")
    if provider == "stub":
        return StubClient()
    client = DeepSeekClient(config)
    if not client.has_credentials():
        if str(client.api_key_env).startswith(("sk-", "Bearer ")):
            logger.warning(
                "检测到密钥可能被误填到 llm.api_key_env；请改为环境变量名"
                "DEEPSEEK_API_KEY，并把密钥只放在 .env"
            )
        logger.warning(
            "未检测到模型密钥，已回退离线桩客户端；"
            "如需真实生成请在 .env 配置 DEEPSEEK_API_KEY"
        )
        return StubClient()
    return client
