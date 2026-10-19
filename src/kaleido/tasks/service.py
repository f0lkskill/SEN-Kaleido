"""异步任务服务：优先级队列 + 后台工作线程 + 状态持久化。

工作线程从队列取任务→执行已注册处理器→把状态写回 vault。
支持失败重试与闲时调度（``defer_off_peak``）。
"""

import threading
from collections.abc import Callable
from datetime import datetime
from time import monotonic, sleep

from kaleido.common.config import load_yaml
from kaleido.common.errors import ConflictError, NotFoundError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.tasks.models import CreateTaskRequest
from kaleido.tasks.queue import TaskQueue
from kaleido.tasks.schedule import is_off_peak
from kaleido.vault import Vault

logger = get_logger("tasks")

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# 任务状态常量，供服务与 API 复用
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

# 处理器签名：接收 payload，返回业务结果字典
Handler = Callable[[dict], dict]


class TaskService:
    """异步任务服务。"""

    def __init__(
        self,
        vault: Vault | None = None,
        config: dict | None = None,
        clock: Callable[[], datetime] | None = None,
        autostart: bool = True,
    ):
        self.config = config or load_yaml("tasks", "tasks")
        self.vault = vault or Vault()
        # 任务落库到 vault 的 tasks 集合（envelope=true，带创建/更新时间）
        self.tasks = self.vault.collection("tasks")
        # 可注入时钟，便于测试闲时逻辑
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._handlers: dict[str, Handler] = {}
        self._queue = TaskQueue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._worker_count = int(self.config.get("worker_count", 2))
        self._schedule_cfg = self.config.get("schedule", {})
        self._defer_poll = float(self._schedule_cfg.get("defer_poll_seconds", 5))
        if autostart:
            self.start()

    # ---- 时钟与时间 ----
    def _now(self) -> str:
        """当前时间字符串。"""
        return self._clock().strftime(_TIME_FORMAT)

    def _is_off_peak(self) -> bool:
        """当前是否处于闲时。"""
        return is_off_peak(self._clock(), self._schedule_cfg)

    # ---- 生命周期 ----
    def start(self) -> None:
        """启动后台工作线程（幂等）。"""
        if self._threads:
            return
        self._stop.clear()
        for index in range(max(1, self._worker_count)):
            thread = threading.Thread(
                target=self._worker_loop, name=f"kaleido-task-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def shutdown(self, timeout: float = 5.0) -> None:
        """停止后台线程并等待退出。"""
        self._stop.set()
        self._queue.wake()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    # ---- 处理器注册 ----
    def register(self, task_type: str, handler: Handler) -> None:
        """注册某类任务的处理器。"""
        self._handlers[task_type] = handler

    def registered_types(self) -> list[str]:
        """返回已注册的任务类型。"""
        return sorted(self._handlers.keys())

    # ---- 用例 ----
    def submit(self, request: CreateTaskRequest) -> dict:
        """提交任务：落库 pending 并入队。"""
        if request.task_type not in self._handlers:
            raise ValidationError(f"未注册的任务类型: {request.task_type}")
        task_id = self.tasks.next_id()
        now = self._now()
        document = {
            "task_id": task_id,
            "task_type": request.task_type,
            "status": PENDING,
            "payload": request.payload,
            "result": None,
            "error": None,
            "priority": request.priority,
            "attempts": 0,
            "max_attempts": max(1, request.max_attempts),
            "defer_off_peak": request.defer_off_peak,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.tasks.put(task_id, document)
        self._queue.push(task_id, request.priority)
        return document

    def get(self, task_id: str) -> dict:
        """读取任务。"""
        try:
            return self.tasks.get(task_id)
        except Exception as exc:
            raise NotFoundError(f"任务不存在: {task_id}") from exc

    def list_tasks(
        self,
        task_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按类型/状态分页列出任务（附带完整字段）。"""
        filters: dict[str, str] = {}
        if task_type:
            filters["task_type"] = task_type
        if status:
            filters["status"] = status
        entries, total = self.tasks.list(filters, page=page, size=size)
        items = []
        for entry in entries:
            try:
                items.append(self.tasks.get(entry["id"]))
            except Exception as exc:  # noqa: BLE001 - 索引残留但分片缺失时跳过
                logger.warning("索引条目 %s 对应分片缺失: %s", entry["id"], exc)
                continue
        return {"total": total, "page": page, "size": size, "items": items}

    def cancel(self, task_id: str) -> dict:
        """取消任务；仅排队中或执行中的任务可取消。"""
        document = self.get(task_id)
        if document.get("status") not in (PENDING, RUNNING):
            raise ConflictError(f"任务当前状态不可取消: {document.get('status')}")
        document["status"] = CANCELLED
        document["updated_at"] = self._now()
        document["finished_at"] = self._now()
        self.tasks.put(task_id, document)
        return document

    def wait(self, task_id: str, timeout: float = 5.0, interval: float = 0.05) -> dict:
        """轮询等待任务进入终态，主要供测试与脚本使用。"""
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            document = self.get(task_id)
            if document.get("status") in (SUCCEEDED, FAILED, CANCELLED):
                return document
            sleep(interval)
        return self.get(task_id)

    # ---- 工作线程 ----
    def _worker_loop(self) -> None:
        """工作线程主循环。"""
        while not self._stop.is_set():
            task_id = self._queue.pop(timeout=0.5)
            if task_id is None:
                continue
            try:
                document = self.tasks.get(task_id)
            except Exception as exc:  # noqa: BLE001 - 任务可能已被删除
                logger.debug("跳过不可读取的任务 %s: %s", task_id, exc)
                continue
            # 只处理仍处于排队态的任务（可能已被取消/执行）
            if document.get("status") != PENDING:
                continue
            # 闲时任务在非闲时重新入队，稍后再试
            if document.get("defer_off_peak") and not self._is_off_peak():
                self._queue.push(task_id, document.get("priority", 0))
                self._stop.wait(self._defer_poll)
                continue
            self._run(task_id, document)

    def _run(self, task_id: str, document: dict) -> None:
        """执行单个任务并写回状态。"""
        document["status"] = RUNNING
        document["attempts"] = int(document.get("attempts", 0)) + 1
        document["started_at"] = self._now()
        document["updated_at"] = self._now()
        self.tasks.put(task_id, document)

        handler = self._handlers.get(document["task_type"])
        try:
            if handler is None:
                raise ValidationError(f"未注册的任务类型: {document['task_type']}")
            result = handler(document.get("payload", {}))
        except Exception as exc:  # noqa: BLE001 - 统一转为失败/重试
            self._handle_failure(task_id, exc)
            return
        self._handle_success(task_id, result)

    def _handle_success(self, task_id: str, result: dict) -> None:
        """成功收尾；若期间被取消则保留取消态。"""
        document = self.tasks.get(task_id)
        if document.get("status") == CANCELLED:
            return
        document["status"] = SUCCEEDED
        document["result"] = result
        document["error"] = None
        document["finished_at"] = self._now()
        document["updated_at"] = self._now()
        self.tasks.put(task_id, document)

    def _handle_failure(self, task_id: str, exc: Exception) -> None:
        """失败收尾：未达上限则重新入队，否则标记失败。"""
        document = self.tasks.get(task_id)
        if document.get("status") == CANCELLED:
            return
        document["error"] = str(exc)
        document["updated_at"] = self._now()
        if int(document.get("attempts", 0)) < int(document.get("max_attempts", 1)):
            document["status"] = PENDING
            self.tasks.put(task_id, document)
            self._queue.push(task_id, document.get("priority", 0))
            return
        document["status"] = FAILED
        document["finished_at"] = self._now()
        self.tasks.put(task_id, document)
