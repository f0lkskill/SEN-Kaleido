"""kaleido-tasks 数据模型。"""

from pydantic import BaseModel, Field


class CreateTaskRequest(BaseModel):
    """提交异步任务的请求体。"""

    task_type: str  # 任务类型键，需已注册处理器，如 forge.generate
    payload: dict = Field(default_factory=dict)  # 处理器所需参数
    priority: int = 0  # 优先级，数值越大越先执行
    max_attempts: int = 1  # 最大尝试次数（含首次）
    defer_off_peak: bool = False  # 是否只在闲时执行（批量生成省成本）


class TaskModel(BaseModel):
    """任务的持久化结构。"""

    task_id: str
    task_type: str
    status: str = "pending"  # pending/running/succeeded/failed/cancelled
    payload: dict = Field(default_factory=dict)
    result: dict | None = None  # 成功时的业务结果
    error: str | None = None  # 失败原因
    priority: int = 0
    attempts: int = 0  # 已尝试次数
    max_attempts: int = 1
    recoveries: int = 0  # 进程中断后的自动恢复次数
    defer_off_peak: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
