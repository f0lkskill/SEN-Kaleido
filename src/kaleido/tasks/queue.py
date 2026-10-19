"""进程内优先级任务队列。

以最小堆实现优先级调度（``priority`` 越大越先执行），并用条件变量
让工作线程在无任务时阻塞等待，避免忙轮询。
"""

import heapq
import itertools
import threading


class TaskQueue:
    """线程安全的优先级队列，存放任务 ID。"""

    def __init__(self):
        self._heap: list[tuple[int, int, str]] = []
        self._counter = itertools.count()
        self._cv = threading.Condition()

    def push(self, task_id: str, priority: int = 0) -> None:
        """入队；优先级高者先出队。"""
        with self._cv:
            # 堆元素：(-priority, 序号, task_id)；序号保证同优先级稳定顺序
            heapq.heappush(self._heap, (-int(priority), next(self._counter), task_id))
            self._cv.notify()

    def pop(self, timeout: float | None = None) -> str | None:
        """出队；超时无任务返回 None。"""
        with self._cv:
            if not self._heap:
                self._cv.wait(timeout)
            if not self._heap:
                return None
            return heapq.heappop(self._heap)[2]

    def wake(self) -> None:
        """唤醒所有等待中的工作线程（用于停机）。"""
        with self._cv:
            self._cv.notify_all()

    def __len__(self) -> int:
        with self._cv:
            return len(self._heap)
