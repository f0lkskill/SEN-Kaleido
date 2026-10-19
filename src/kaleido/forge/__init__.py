"""kaleido-forge 模块：多模态生成层。

基于学生画像与分层 Prompt 模板，调用云端大模型生成特教资源；
生成结果写入 vault 的 ``resources`` 集合，初始状态为 ``draft``。
"""

from kaleido.forge.llm_client import DeepSeekClient, LLMClient, LLMResult, StubClient, create_client
from kaleido.forge.models import GeneratedResource, GenerateRequest
from kaleido.forge.service import ForgeService

__all__ = [
    "DeepSeekClient",
    "ForgeService",
    "GenerateRequest",
    "GeneratedResource",
    "LLMClient",
    "LLMResult",
    "StubClient",
    "create_client",
]
