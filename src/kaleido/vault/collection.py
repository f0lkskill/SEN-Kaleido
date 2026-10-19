"""集合（命名空间）实现。

在 :class:`~kaleido.vault.jsonstore.JsonStore` 之上提供文档 CRUD、
自增 ID、幂等键、内存索引与条件分页查询。索引与分片的一致性策略：
**先写分片、后写索引**，并以分片为事实来源，索引可随时重建。
"""

import json
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from kaleido.vault.jsonstore import JsonStore
from kaleido.vault.models import CollectionSpec

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


def _dig(data: dict, path: str) -> Any:
    """按点路径取值，如 ``attributes.disability``；缺失返回 None。"""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _matches(entry: dict, key: str, value: Any) -> bool:
    """索引条目字段与过滤值比较。

    数组型字段（如障碍类型列表）采用"包含"语义：过滤值命中数组中
    任一项即视为匹配；其余字段字符串化后相等即可。
    """
    actual = entry.get(key)
    if isinstance(actual, list):
        return str(value) in [str(item) for item in actual]
    return str(actual) == str(value)


class Collection:
    """一个集合：一组同构文档 + 其索引。"""

    def __init__(self, spec: CollectionSpec, data_dir: str | Path):
        self.spec = spec
        self.name = spec.name
        self.root = Path(data_dir) / spec.name
        self.store = JsonStore(self.root)
        self.index_path = self.root / "index.json"
        self._lock = RLock()  # 进程内串行化
        # 初始化索引时也持锁，避免与其它进程的替换写冲突
        with self.store.lock():
            self._index = self._load_index()

    def _empty_index(self) -> dict:
        """空索引结构：counter 计数器、entries 索引条目、idempotency 幂等键。"""
        return {"counter": 0, "entries": {}, "idempotency": {}}

    def _load_index(self) -> dict:
        """读取索引文件；缺失或损坏时回退为空索引。

        注意：Windows 上索引文件可能正被原子替换而瞬时不可读（PermissionError），
        此时必须重试而非直接回退空索引，否则会导致计数器归零、ID 重复。
        """
        if not self.index_path.exists():
            return self._empty_index()
        for _ in range(20):
            try:
                with self.index_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except PermissionError:
                # 瞬时占用，稍后重试
                time.sleep(0.02)
                continue
            except FileNotFoundError:
                # 替换间隙文件短暂消失，稍后重试
                time.sleep(0.02)
                continue
            except json.JSONDecodeError:
                # 内容损坏（原子写不应产生）则回退空索引
                return self._empty_index()
            if not isinstance(data, dict):
                return self._empty_index()
            for key, value in self._empty_index().items():
                data.setdefault(key, value)
            return data
        # 多次仍不可读时保守回退，避免直接崩溃
        return self._empty_index()

    def _write_index(self) -> None:
        """加锁持久化索引。"""
        self.store.write_path_atomic(self.index_path, self._index)

    def _reload(self) -> None:
        """在文件锁下重读索引，感知其它实例的写入。"""
        with self.store.lock():
            self._index = self._load_index()

    def next_id(self) -> str:
        """分配下一个自增 ID（跨进程安全：重读索引后递增再落盘）。"""
        with self._lock, self.store.lock():
            self._index = self._load_index()
            counter = int(self._index.get("counter", 0)) + 1
            self._index["counter"] = counter
            self.store.write_unlocked(self.index_path, self._index)
        return f"{self.spec.id_prefix}_{counter:0{self.spec.id_zerofill}d}"

    def put(
        self, doc_id: str, payload: dict, *, idempotency_key: str | None = None
    ) -> str:
        """写入文档（新增或覆盖），并更新索引与幂等键。"""
        with self._lock:
            path = self.store.path_for(doc_id)
            now = _now()
            doc: Any = payload
            if self.spec.envelope:
                # 包裹模式：保留原 created_at，刷新 updated_at
                created = now
                if path.exists():
                    try:
                        created = self.store.read(doc_id).get("created_at", now)
                    except Exception:  # noqa: BLE001
                        created = now
                doc = {
                    "id": doc_id,
                    "created_at": created,
                    "updated_at": now,
                    "payload": payload,
                }
            # 先写分片
            self.store.write_atomic(doc_id, doc)
            # 后写索引（重读以避免覆盖其它实例的条目）
            with self.store.lock():
                self._index = self._load_index()
                entry = {field: _dig(payload, field) for field in self.spec.index_fields}
                self._index.setdefault("entries", {})[doc_id] = entry
                if idempotency_key and self.spec.idempotent:
                    self._index.setdefault("idempotency", {})[idempotency_key] = doc_id
                self.store.write_unlocked(self.index_path, self._index)
        return doc_id

    def get(self, doc_id: str) -> dict:
        """读取文档业务内容（包裹模式自动解包）。"""
        raw = self.store.read(doc_id)
        if self.spec.envelope and isinstance(raw, dict) and "payload" in raw:
            return raw["payload"]
        return raw

    def delete(self, doc_id: str) -> None:
        """删除文档并清理索引与相关幂等键。"""
        with self._lock:
            self.store.delete(doc_id)
            with self.store.lock():
                self._index = self._load_index()
                self._index.get("entries", {}).pop(doc_id, None)
                for key, value in list(self._index.get("idempotency", {}).items()):
                    if value == doc_id:
                        del self._index["idempotency"][key]
                self.store.write_unlocked(self.index_path, self._index)

    def find_by_key(self, key: str | None) -> str | None:
        """按幂等键查找文档 ID。"""
        if not key:
            return None
        self._reload()
        return self._index.get("idempotency", {}).get(key)

    def list(
        self,
        filters: dict[str, Any] | None = None,
        *,
        page: int = 1,
        size: int = 20,
        sort: str | None = None,
    ) -> tuple[list[dict], int]:
        """按索引字段过滤并分页，返回 (当前页条目, 总条数)。"""
        with self._lock:
            self._reload()
            items: list[dict] = []
            for doc_id, entry in self._index.get("entries", {}).items():
                if filters and not all(
                    _matches(entry, key, value) for key, value in filters.items()
                ):
                    continue
                items.append({"id": doc_id, **entry})
        if sort:
            # 字符串化后排序，避免 None 与不可比较类型
            items.sort(key=lambda item: str(item.get(sort)))
        total = len(items)
        start = (page - 1) * size
        return items[start : start + size], total

    def _read_full(self, doc_id: str) -> dict:
        """读取完整文档：包裹模式下合并 envelope 元数据与业务内容。"""
        raw = self.store.read(doc_id)
        if self.spec.envelope and isinstance(raw, dict) and "payload" in raw:
            meta = {key: value for key, value in raw.items() if key != "payload"}
            payload = raw["payload"] if isinstance(raw["payload"], dict) else {}
            return {**meta, **payload}
        return raw

    def list_full(
        self,
        filters: dict[str, Any] | None = None,
        *,
        page: int = 1,
        size: int = 20,
        sort: str | None = None,
    ) -> tuple[list[dict], int]:
        """按索引过滤分页，但返回完整文档（含正文与创建/更新时间）。

        与 :meth:`list` 的差别：``list`` 只返回索引字段，用于轻量筛选；
        ``list_full`` 额外回读分片，适合需要展示正文的列表（如资源库）。
        """
        items, total = self.list(filters, page=page, size=size, sort=sort)
        return [self._read_full(item["id"]) for item in items], total

    def iter_all(self) -> Iterator[dict]:
        """迭代全部文档业务内容。"""
        for doc_id in self.store.list_ids():
            yield self.get(doc_id)

    def reindex(self) -> None:
        """以分片为事实来源重建索引条目（保留 counter 与幂等键）。"""
        with self._lock:
            entries: dict[str, dict] = {}
            for doc_id in self.store.list_ids():
                raw = self.store.read(doc_id)
                payload = raw["payload"] if self.spec.envelope and "payload" in raw else raw
                entries[doc_id] = {
                    field: _dig(payload, field) for field in self.spec.index_fields
                }
            with self.store.lock():
                self._index = self._load_index()
                self._index["entries"] = entries
                self.store.write_unlocked(self.index_path, self._index)
