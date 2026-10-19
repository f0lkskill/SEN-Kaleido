"""底层 JSON 文件读写。

提供原子写（临时文件 + ``os.replace``）、文件锁（``portalocker``）与安全读，
是 :class:`~kaleido.vault.collection.Collection` 的存储基座。
"""

import json
import os
from pathlib import Path
from typing import Any

import portalocker

from kaleido.common.errors import NotFoundError, StorageError


class JsonStore:
    """单个目录下的 JSON 文件操作。"""

    def __init__(self, root: str | Path, lock_timeout: float = 10.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # 集合级文件锁，跨进程串行化写入
        self.lock_path = self.root / ".lock"
        self.lock_timeout = lock_timeout

    def path_for(self, doc_id: str) -> Path:
        """文档 ID 对应的文件路径。"""
        return self.root / f"{doc_id}.json"

    def exists(self, doc_id: str) -> bool:
        """文档是否存在。"""
        return self.path_for(doc_id).exists()

    def read(self, doc_id: str) -> Any:
        """按 ID 读取文档。"""
        return self.read_path(self.path_for(doc_id))

    def read_path(self, path: Path) -> Any:
        """读取指定路径的 JSON 文件。"""
        if not path.exists():
            raise NotFoundError(f"文档不存在: {path.name}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise StorageError(f"文档解析失败: {path}: {exc}") from exc
        except OSError as exc:
            raise StorageError(f"读取失败: {path}: {exc}") from exc

    def write_atomic(self, doc_id: str, payload: Any) -> None:
        """加锁原子写入文档。"""
        self.write_path_atomic(self.path_for(doc_id), payload)

    def write_path_atomic(self, path: Path, payload: Any) -> None:
        """加锁原子写入指定路径。"""
        with self.lock():
            self._write(path, payload)

    def write_unlocked(self, path: Path, payload: Any) -> None:
        """不加锁写入（调用方需已持锁，如索引与文档同批更新）。"""
        self._write(path, payload)

    def _write(self, path: Path, payload: Any) -> None:
        """先写临时文件再 ``os.replace``，保证原子性。"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f"写入失败: {path}: {exc}") from exc

    def delete(self, doc_id: str) -> None:
        """删除文档，不存在时抛出 NotFoundError。"""
        path = self.path_for(doc_id)
        if not path.exists():
            raise NotFoundError(f"文档不存在: {doc_id}")
        try:
            path.unlink()
        except OSError as exc:
            raise StorageError(f"删除失败: {path}: {exc}") from exc

    def lock(self):
        """返回可作 ``with`` 使用的文件锁。"""
        return portalocker.Lock(str(self.lock_path), timeout=self.lock_timeout)

    def list_ids(self) -> list[str]:
        """列出所有文档 ID（排除索引文件）。"""
        return sorted(
            path.stem
            for path in self.root.glob("*.json")
            if path.name != "index.json"
        )
