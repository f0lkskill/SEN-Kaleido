"""kaleido-profile 模块：学生评价模型（类型层 / 属性层 / 评价框架层）。

对外导出核心组件，其它模块（forge / tasks / loop 等）通过本层获取
学生画像与个性化评价框架，无需关心配置与存储细节。
"""

from kaleido.profile.attributes import AttributeSchema
from kaleido.profile.framework import FrameworkEngine
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.profile.taxonomy import Taxonomy

__all__ = [
    "AttributeSchema",
    "FrameworkEngine",
    "ProfileService",
    "StudentRepository",
    "Taxonomy",
]
