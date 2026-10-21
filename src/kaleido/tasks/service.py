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
        self._max_recoveries = int(self.config.get("max_recoveries", 3))
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
        count = max(1, self._worker_count)
        for index in range(count):
            thread = threading.Thread(
                target=self._worker_loop, name=f"kaleido-task-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        logger.info("任务工作线程已启动: %d 个", count)

    def shutdown(self, timeout: float = 5.0) -> None:
        """停止后台线程并等待退出。"""
        self._stop.set()
        self._queue.wake()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()
        logger.info("任务工作线程已停止")

    # ---- 处理器注册 ----
    def register(self, task_type: str, handler: Handler) -> None:
        """注册某类任务的处理器。"""
        self._handlers[task_type] = handler

    def registered_types(self) -> list[str]:
        """返回已注册的任务类型。"""
        return sorted(self._handlers.keys())

    # ---- 进程重启恢复 ----
    def recover(self) -> dict:
        """恢复上次进程遗留的未完成任务。

        需在各模块注册完处理器后调用。``pending`` 任务重新入队；
        ``running`` 任务视为上次进程中断：回退该次尝试并重新入队，
        超过 ``max_recoveries`` 才标记失败。未注册类型的任务保持原状，
        以便注册后再恢复。
        """
        stats = {"requeued": 0, "failed": 0, "skipped": 0}
        for document in self.tasks.iter_all():
            status = document.get("status")
            if status not in (PENDING, RUNNING):
                continue
            task_id = str(document.get("task_id") or "")
            task_type = str(document.get("task_type") or "")
            if not task_id or task_type not in self._handlers:
                stats["skipped"] += 1
                logger.warning(
                    "跳过不可恢复任务: id=%s type=%s status=%s",
                    task_id,
                    task_type,
                    status,
                )
                continue
            if status == RUNNING:
                recoveries = int(document.get("recoveries", 0)) + 1
                document["recoveries"] = recoveries
                if recoveries > self._max_recoveries:
                    document["status"] = FAILED
                    document["error"] = "任务执行中断，且超过自动恢复上限"
                    document["finished_at"] = self._now()
                    document["updated_at"] = self._now()
                    self.tasks.put(task_id, document)
                    stats["failed"] += 1
                    logger.error(
                        "任务中断且超过恢复上限: id=%s type=%s recoveries=%d",
                        task_id,
                        task_type,
                        recoveries,
                    )
                    continue
                document["status"] = PENDING
                document["attempts"] = max(0, int(document.get("attempts", 0)) - 1)
                document["error"] = "任务执行中断，已重新排队"
                document["finished_at"] = None
                logger.warning(
                    "恢复中断任务: id=%s type=%s recoveries=%d",
                    task_id,
                    task_type,
                    recoveries,
                )
            document["updated_at"] = self._now()
            self.tasks.put(task_id, document)
            self._queue.push(task_id, int(document.get("priority", 0)))
            stats["requeued"] += 1
        logger.info("任务恢复完成: %s", stats)
        return stats

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
            "recoveries": 0,
            "defer_off_peak": request.defer_off_peak,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.tasks.put(task_id, document)
        self._queue.push(task_id, request.priority)
        logger.info(
            "提交任务: id=%s type=%s priority=%s defer_off_peak=%s",
            task_id,
            request.task_type,
            request.priority,
            request.defer_off_peak,
        )
        return document

    def get(self, task_id: str) -> dict:
        """读取任务。"""
        try:
            return self.tasks.get(task_id)
        except Exception as exc:
            raise NotFoundError(f"任务不存在: {task_id}") from exc

    def _get_or_none(self, task_id: str) -> dict | None:
        """读取任务，缺失时返回 ``None``（供外部任务收尾）。"""
        try:
            return self.tasks.get(task_id)
        except Exception:  # noqa: BLE001 - 任务可能已被删除
            logger.warning("外部任务不存在，跳过收尾: id=%s", task_id)
            return None

    def create_external(
        self, task_type: str, payload: dict | None = None
    ) -> dict:
        """登记由 HTTP 请求等外部路径直接执行的任务（不入队）。

        用于流式生成等无法交给工作线程执行、但需要在任务面板可见的
        长任务：先建 ``pending`` 记录，执行方再调用 :meth:`mark_running`
        / :meth:`mark_succeeded` / :meth:`mark_failed` 更新状态。
        """
        task_id = self.tasks.next_id()
        now = self._now()
        document = {
            "task_id": task_id,
            "task_type": task_type,
            "status": PENDING,
            "payload": payload or {},
            "result": None,
            "error": None,
            "priority": 0,
            "attempts": 0,
            "max_attempts": 1,
            "recoveries": 0,
            "defer_off_peak": False,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.tasks.put(task_id, document)
        logger.info("登记外部任务: id=%s type=%s", task_id, task_type)
        return document

    def mark_running(self, task_id: str) -> None:
        """把外部任务标记为执行中。"""
        document = self._get_or_none(task_id)
        if document is None or document.get("status") == CANCELLED:
            return
        document["status"] = RUNNING
        document["attempts"] = int(document.get("attempts", 0)) + 1
        document["started_at"] = self._now()
        document["updated_at"] = self._now()
        self.tasks.put(task_id, document)

    def mark_succeeded(self, task_id: str, result: dict | None = None) -> None:
        """把外部任务标记为成功；期间被取消则保留取消态。"""
        document = self._get_or_none(task_id)
        if document is None or document.get("status") == CANCELLED:
            return
        document["status"] = SUCCEEDED
        document["result"] = result
        document["error"] = None
        document["finished_at"] = self._now()
        document["updated_at"] = self._now()
        self.tasks.put(task_id, document)
        logger.info("外部任务完成: id=%s", task_id)

    def mark_failed(self, task_id: str, error: str) -> None:
        """把外部任务标记为失败。"""
        document = self._get_or_none(task_id)
        if document is None or document.get("status") == CANCELLED:
            return
        document["status"] = FAILED
        document["error"] = error
        document["finished_at"] = self._now()
        document["updated_at"] = self._now()
        self.tasks.put(task_id, document)
        logger.error("外部任务失败: id=%s error=%s", task_id, error)

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
        logger.info("取消任务: id=%s", task_id)
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
        logger.info(
            "开始执行任务: id=%s type=%s attempt=%s",
            task_id,
            document.get("task_type"),
            document.get("attempts"),
        )

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
        logger.info("任务执行完成: id=%s", task_id)

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
            logger.warning(
                "任务失败将重试: id=%s attempt=%s error=%s",
                task_id,
                document.get("attempts"),
                exc,
            )
            return
        document["status"] = FAILED
        document["finished_at"] = self._now()
        self.tasks.put(task_id, document)
        logger.error("任务最终失败: id=%s error=%s", task_id, exc)
