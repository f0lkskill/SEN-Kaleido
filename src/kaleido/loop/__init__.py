"""kaleido-loop：反馈迭代层。

把已审核的课堂证据汇总为可追溯的评价快照，供画像展示、匹配与
资源回炉决策使用。当前阶段只做规则聚合，不调用大模型。
"""

from kaleido.loop.models import EvaluationSnapshot, LoopEvaluateRequest
from kaleido.loop.repository import EvaluationRepository
from kaleido.loop.service import LoopService

__all__ = [
    "EvaluationRepository",
    "EvaluationSnapshot",
    "LoopEvaluateRequest",
    "LoopService",
]
