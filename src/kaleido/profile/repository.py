"""学生画像持久化（vault 适配器）。

存储实现的通用能力（分片、原子写、文件锁、索引）已下沉到 `kaleido-vault`；
本类只保留**领域语义**：集合名、索引字段、ID 前缀与幂等开关，
把 profile 模型与 vault 的文档接口互相转换。
"""

from pathlib import Path

from kaleido.profile.models.evaluation import StudentEvaluationProfile
from kaleido.vault import Vault


class StudentRepository:
    """学生档案仓库（基于 vault 的 `students` 集合，裸文档模式）。"""

    def __init__(self, data_dir: str | Path | None = None, vault: Vault | None = None):
        # 传入 data_dir 便于测试使用临时目录；vault 可整体注入
        self.vault = vault or Vault(data_dir)
        self.collection = self.vault.collection("students")

    def next_id(self) -> str:
        """分配下一个档案 ID，格式 p_0001。"""
        return self.collection.next_id()

    def find_by_request(self, request_id: str | None) -> str | None:
        """按幂等请求 ID 查找已存在的档案 ID。"""
        return self.collection.find_by_key(request_id)

    def save(self, profile: StudentEvaluationProfile, request_id: str | None = None) -> None:
        """保存档案（同时登记可选的幂等键）。"""
        self.collection.put(
            profile.profile_id,
            profile.model_dump(),
            idempotency_key=request_id,
        )

    def get(self, profile_id: str) -> StudentEvaluationProfile:
        """读取单个档案，不存在时抛出 NotFoundError。"""
        return StudentEvaluationProfile(**self.collection.get(profile_id))

    def delete(self, profile_id: str) -> None:
        """删除档案。"""
        self.collection.delete(profile_id)

    def list(
        self,
        disability: str | None = None,
        cognitive_level: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        """按条件分页查询档案元信息，返回 (当前页条目, 总条数)。

        索引字段使用点路径，此处转换为列表页面向外暴露的扁平结构。
        """
        filters: dict[str, str] = {}
        if disability:
            filters["attributes.disability"] = disability
        if cognitive_level:
            filters["attributes.cognitive_level"] = cognitive_level
        items, total = self.collection.list(filters, page=page, size=size)
        results = [
            {
                "profile_id": item["id"],
                "name": item.get("name"),
                "disability": item.get("attributes.disability"),
                "severity": item.get("attributes.severity"),
                "cognitive_level": item.get("attributes.cognitive_level"),
            }
            for item in items
        ]
        return results, total
