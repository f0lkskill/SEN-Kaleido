"""集合注册中心。

按 ``configs/vault/vault.yaml`` 创建并缓存各集合，是业务模块访问存储的入口。
"""

from pathlib import Path

from kaleido.common.config import load_yaml
from kaleido.common.paths import DATA_DIR
from kaleido.vault.collection import Collection
from kaleido.vault.models import CollectionSpec


class Vault:
    """JSON 文档库。"""

    def __init__(self, data_dir: str | Path | None = None, config: dict | None = None):
        # 传入 data_dir 便于测试使用临时目录
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        config = config or load_yaml("vault", "vault")
        defaults: dict = config.get("defaults", {})
        raw_collections: dict = config.get("collections", {})
        # 合并默认项与各集合定义
        self._specs: dict[str, CollectionSpec] = {
            name: CollectionSpec(name=name, **{**defaults, **raw})
            for name, raw in raw_collections.items()
        }
        self._collections: dict[str, Collection] = {}

    def collection(self, name: str) -> Collection:
        """获取集合；未在配置中声明时按默认规格惰性创建。"""
        if name not in self._collections:
            spec = self._specs.get(name) or CollectionSpec(name=name)
            self._collections[name] = Collection(spec, self.data_dir)
        return self._collections[name]

    def namespaces(self) -> list[str]:
        """返回已声明的集合名。"""
        return sorted(self._specs.keys())
