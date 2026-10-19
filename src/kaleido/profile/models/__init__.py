"""profile 模块的数据模型导出入口。

集中导出类型层、属性层、评价框架层的模型，方便其它模块 ``from kaleido.profile.models import X``。
"""

from kaleido.profile.models.evaluation import (
    EvaluationFramework,
    Indicator,
    ObservationItem,
    Rubric,
    StudentEvaluationProfile,
)
from kaleido.profile.models.student import (
    CreateStudentRequest,
    StudentAttributes,
    StudentAttributesInput,
    UpdateStudentRequest,
)
from kaleido.profile.models.taxonomy import StudentType

__all__ = [
    "StudentType",
    "StudentAttributesInput",
    "StudentAttributes",
    "CreateStudentRequest",
    "UpdateStudentRequest",
    "Rubric",
    "ObservationItem",
    "Indicator",
    "EvaluationFramework",
    "StudentEvaluationProfile",
]
