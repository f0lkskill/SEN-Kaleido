"""学生画像持久化。

采用本地 JSON 分片存储，适合单写入方（处理基站）的局域网部署：
- ``data/students/<profile_id>.json`` 保存完整档案；
- ``data/students/index.json`` 保存元信息索引与幂等请求映射，加速列表查询；
- 通过文件锁 + 临时文件替换实现原子写，避免并发写坏文件。
"""

import json
import os
from pathlib import Path
from threading import RLock

import portalocker

from kaleido.common.errors import NotFoundError, StorageError
from kaleido.common.paths import DATA_DIR
from kaleido.profile.models.evaluation import StudentEvaluationProfile


class StudentRepository:
    """学生档案仓库（JSON 文件存储）。"""

    def __init__(self, data_dir: str | Path | None = None):
        # 传入 data_dir 便于测试使用临时目录
        base = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir = base / "students"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "index.json"
        self.lock_path = self.data_dir / ".lock"
        self._lock = RLock()  # 进程内互斥
        self._index = self._load_index()

    def _empty_index(self) -> dict:
        """空索引结构：counter 用于生成自增 ID，requests 用于幂等去重。"""
        return {"counter": 0, "profiles": {}, "requests": {}}

    def _load_index(self) -> dict:
        """读取索引文件，不存在时返回空索引。"""
        if not self.index_path.exists():
            return self._empty_index()
        with self.index_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _atomic_write_json(self, path: Path, payload: dict) -> None:
        """加文件锁并原子写入 JSON：先写临时文件再 replace。"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with portalocker.Lock(str(self.lock_path), timeout=10):
                with tmp.open("w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f"写入失败: {path}: {exc}") from exc

    def _write_index(self) -> None:
        """持久化索引。"""
        self._atomic_write_json(self.index_path, self._index)

    def _profile_path(self, profile_id: str) -> Path:
        """档案文件路径。"""
        return self.data_dir / f"{profile_id}.json"

    def next_id(self) -> str:
        """生成下一个自增档案 ID，格式 p_0001。"""
        with self._lock:
            self._index["counter"] = self._index.get("counter", 0) + 1
            return f"p_{self._index['counter']:04d}"

    def find_by_request(self, request_id: str | None) -> str | None:
        """按幂等请求 ID 查找已存在的档案 ID。"""
        if not request_id:
            return None
        return self._index.get("requests", {}).get(request_id)

    def save(self, profile: StudentEvaluationProfile, request_id: str | None = None) -> None:
        """保存档案，并同步更新索引与（可选的）幂等请求映射。"""
        with self._lock:
            self._atomic_write_json(self._profile_path(profile.profile_id), profile.model_dump())
            # 索引只存列表页需要的元信息，避免读取整个档案
            self._index.setdefault("profiles", {})[profile.profile_id] = {
                "name": profile.name,
                "disability": profile.attributes.disability,
                "severity": profile.attributes.severity,
                "cognitive_level": profile.attributes.cognitive_level,
            }
            if request_id:
                self._index.setdefault("requests", {})[request_id] = profile.profile_id
            self._write_index()

    def get(self, profile_id: str) -> StudentEvaluationProfile:
        """读取单个档案，不存在时抛出 NotFoundError。"""
        path = self._profile_path(profile_id)
        if not path.exists():
            raise NotFoundError(f"学生不存在: {profile_id}")
        with path.open("r", encoding="utf-8") as handle:
            return StudentEvaluationProfile(**json.load(handle))

    def delete(self, profile_id: str) -> None:
        """删除档案并更新索引。"""
        with self._lock:
            path = self._profile_path(profile_id)
            if not path.exists():
                raise NotFoundError(f"学生不存在: {profile_id}")
            path.unlink()
            self._index.get("profiles", {}).pop(profile_id, None)
            self._write_index()

    def list(
        self,
        disability: str | None = None,
        cognitive_level: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        """按条件分页查询档案元信息，返回 (当前页条目, 总条数)。"""
        items = []
        for profile_id, meta in self._index.get("profiles", {}).items():
            if disability and meta.get("disability") != disability:
                continue
            if cognitive_level and meta.get("cognitive_level") != cognitive_level:
                continue
            items.append({"profile_id": profile_id, **meta})
        total = len(items)
        start = (page - 1) * size
        return items[start : start + size], total
