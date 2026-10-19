"""kaleido-vault 模块：本地 JSON 文档库（数据层 / 支撑模块）。

对各业务模块提供统一的持久化与检索能力：分片存储、原子写、文件锁、
内存索引、CRUD、分页与幂等。
"""

from kaleido.vault.collection import Collection
from kaleido.vault.jsonstore import JsonStore
from kaleido.vault.models import CollectionSpec
from kaleido.vault.vault import Vault

__all__ = ["Vault", "Collection", "JsonStore", "CollectionSpec"]
