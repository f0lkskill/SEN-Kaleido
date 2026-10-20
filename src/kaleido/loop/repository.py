"""评价快照持久化（vault 适配器）。"""

from pathlib import Path

from kaleido.common.errors import NotFoundError
from kaleido.loop.models import EvaluationSnapshot
from kaleido.vault import Vault


class EvaluationRepository:
    """评价快照仓库（基于 vault 的 evaluations 集合）。"""

    def __init__(self, data_dir: str | Path | None = None, vault: Vault | None = None):
        self.vault = vault or Vault(data_dir)
        self.collection = self.vault.collection("evaluations")

    def next_id(self) -> str:
        """分配下一个快照 ID，格式 es_00001。"""
        return self.collection.next_id()

    def save(self, snapshot: EvaluationSnapshot) -> None:
        """保存快照。"""
        self.collection.put(snapshot.snapshot_id, snapshot.model_dump())

    def get(self, snapshot_id: str) -> EvaluationSnapshot:
        """读取快照，不存在时抛出 NotFoundError。"""
        return EvaluationSnapshot(**self.collection.get(snapshot_id))

    def list(
        self,
        student_id: str | None = None,
        *,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        """按学生列出快照，按计算时间倒序后分页。"""
        filters = {"student_id": student_id} if student_id else {}
        items, _ = self.collection.list_full(filters, page=1, size=100000)
        items.sort(key=lambda item: str(item.get("computed_at") or ""), reverse=True)
        total = len(items)
        start = (page - 1) * size
        return items[start : start + size], total

    def latest(self, student_id: str) -> EvaluationSnapshot:
        """读取某学生最近一次快照。"""
        items, _ = self.list(student_id, page=1, size=1)
        if not items:
            raise NotFoundError(f"学生尚未生成评价快照: {student_id}")
        return EvaluationSnapshot(**items[0])
