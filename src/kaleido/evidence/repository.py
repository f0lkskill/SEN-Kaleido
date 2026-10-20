"""证据持久化（vault 适配器）。

复用 vault 的分片存储、原子写与索引；本类只保留证据集合的领域语义。
"""

from pathlib import Path

from kaleido.evidence.models import EvidenceRecord
from kaleido.vault import Vault


class EvidenceRepository:
    """证据仓库（基于 vault 的 `evidence` 集合，裸文档模式）。"""

    def __init__(self, data_dir: str | Path | None = None, vault: Vault | None = None):
        # 传入 data_dir 便于测试；vault 可整体注入以与其它模块共享实例
        self.vault = vault or Vault(data_dir)
        self.collection = self.vault.collection("evidence")

    def next_id(self) -> str:
        """分配下一个证据 ID，格式 e_00001。"""
        return self.collection.next_id()

    def save(self, record: EvidenceRecord) -> None:
        """保存证据记录（新增或覆盖）。"""
        self.collection.put(record.evidence_id, record.model_dump())

    def get(self, evidence_id: str) -> EvidenceRecord:
        """读取单条证据，不存在时抛出 NotFoundError。"""
        return EvidenceRecord(**self.collection.get(evidence_id))

    def delete(self, evidence_id: str) -> None:
        """删除证据记录。"""
        self.collection.delete(evidence_id)

    def list(
        self,
        filters: dict[str, str] | None = None,
        *,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        """按索引字段过滤并分页，返回完整记录。"""
        return self.collection.list_full(filters, page=page, size=size)

    def iter_all(self):
        """迭代全部证据记录，供统计使用。"""
        yield from self.collection.iter_all()
