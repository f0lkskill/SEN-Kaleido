"""类型层：加载障碍分类体系并提供查询。

把配置文件 ``student_types.yaml`` 转换为 :class:`StudentType` 集合，
是属性解析与评价框架生成的基础。
"""

from kaleido.common.errors import ConfigError, ValidationError
from kaleido.profile.config_loader import load_config
from kaleido.profile.models.taxonomy import StudentType


class Taxonomy:
    """障碍类型分类体系。"""

    def __init__(self, types: dict[str, StudentType]):
        # 以类型键为索引，便于 O(1) 查询
        self._types = types

    @classmethod
    def load(cls) -> "Taxonomy":
        """从配置文件加载类型体系。"""
        raw = load_config("student_types").get("student_types")
        if not raw:
            raise ConfigError("student_types.yaml 缺少 student_types 配置")
        types = {key: StudentType(key=key, **value) for key, value in raw.items()}
        return cls(types)

    def get(self, key: str) -> StudentType:
        """按键获取类型，不存在时抛出 ValidationError。"""
        if key not in self._types:
            raise ValidationError(f"未知障碍类型: {key}")
        return self._types[key]

    def all(self) -> list[StudentType]:
        """返回全部类型。"""
        return list(self._types.values())

    def keys(self) -> list[str]:
        """返回全部类型键。"""
        return list(self._types.keys())
