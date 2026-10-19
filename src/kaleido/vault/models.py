"""vault 数据模型。

描述集合（命名空间）的存储规格，由配置驱动实例化。
"""

from pydantic import BaseModel, Field


class CollectionSpec(BaseModel):
    """集合（命名空间）存储规格。"""

    name: str  # 集合名，即数据子目录名（如 students）
    id_prefix: str = "d"  # 文档 ID 前缀（如 p → p_0001）
    id_zerofill: int = 4  # ID 数字部分补零位宽
    envelope: bool = True  # 是否包裹元数据（id/created_at/updated_at/payload）
    idempotent: bool = False  # 是否启用幂等键去重
    index_fields: list[str] = Field(default_factory=list)  # 建索引的 payload 点路径字段
