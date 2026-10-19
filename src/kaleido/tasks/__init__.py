"""kaleido-tasks 模块：异步任务队列与闲时调度。

职责：
- 接收生成/质检/迭代等耗时任务，交由后台线程异步执行；
- 任务状态持久化到 vault 的 ``tasks`` 集合，支持查询、取消与重试；
- 支持把批量任务调度到闲时（夜间/周末/节假日）执行以降低成本。
"""

from kaleido.tasks.models import CreateTaskRequest, TaskModel
from kaleido.tasks.schedule import is_off_peak
from kaleido.tasks.service import TaskService

__all__ = ["CreateTaskRequest", "TaskModel", "TaskService", "is_off_peak"]
