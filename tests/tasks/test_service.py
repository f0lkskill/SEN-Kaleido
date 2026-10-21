"""异步任务服务测试：执行、失败重试、取消与闲时调度。"""

import sys
from datetime import datetime
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.common.errors import ConflictError, ValidationError
from kaleido.tasks.models import CreateTaskRequest
from kaleido.tasks.recording import record_stream
from kaleido.tasks.service import (
    CANCELLED,
    FAILED,
    PENDING,
    SUCCEEDED,
    TaskService,
)
from kaleido.vault import Vault


class Clock:
    """可手动推进的时钟，用于测试闲时逻辑。"""

    def __init__(self, current: datetime):
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _service(tmp_path, clock=None, config=None):
    """构建测试用服务：单工作线程、关闭默认启动。"""
    base_config = {
        "worker_count": 1,
        "schedule": {
            "defer_poll_seconds": 0.05,
            "off_peak": {
                "weekends": True,
                "holidays": [],
                "windows": [{"start": "22:00", "end": "07:00"}],
            },
        },
    }
    if config:
        base_config.update(config)
    return TaskService(
        vault=Vault(data_dir=tmp_path),
        config=base_config,
        clock=clock,
        autostart=False,
    )


def test_successful_execution(tmp_path):
    """提交任务后由工作线程执行并返回结果。"""
    service = _service(tmp_path)
    service.register("echo", lambda payload: {"echo": payload.get("value")})
    service.start()
    try:
        task = service.submit(CreateTaskRequest(task_type="echo", payload={"value": 42}))
        done = service.wait(task["task_id"])
        assert done["status"] == SUCCEEDED
        assert done["result"] == {"echo": 42}
        assert done["attempts"] == 1
    finally:
        service.shutdown()


def test_unknown_type_rejected(tmp_path):
    """未注册的任务类型直接拒绝。"""
    service = _service(tmp_path)
    try:
        import pytest

        with pytest.raises(ValidationError):
            service.submit(CreateTaskRequest(task_type="missing", payload={}))
    finally:
        service.shutdown()


def test_failure_retries_then_fails(tmp_path):
    """处理器持续失败时按 max_attempts 重试，最终标记失败。"""
    service = _service(tmp_path)

    def boom(payload):
        raise RuntimeError("boom")

    service.register("boom", boom)
    service.start()
    try:
        task = service.submit(
            CreateTaskRequest(task_type="boom", payload={}, max_attempts=2)
        )
        done = service.wait(task["task_id"])
        assert done["status"] == FAILED
        assert done["attempts"] == 2
        assert "boom" in (done["error"] or "")
    finally:
        service.shutdown()


def test_cancel_pending(tmp_path):
    """未启动工作线程时任务保持 pending，可被取消。"""
    service = _service(tmp_path)
    service.register("echo", lambda payload: {"ok": True})
    try:
        task = service.submit(CreateTaskRequest(task_type="echo", payload={}))
        assert service.get(task["task_id"])["status"] == PENDING
        cancelled = service.cancel(task["task_id"])
        assert cancelled["status"] == CANCELLED

        import pytest

        with pytest.raises(ConflictError):
            service.cancel(task["task_id"])
    finally:
        service.shutdown()


def test_defer_off_peak(tmp_path):
    """标记闲时执行的任务在高峰时段不执行，进入闲时后执行。"""
    # 起始为工作日白天（高峰）
    clock = Clock(datetime(2026, 10, 5, 15, 0))
    service = _service(tmp_path, clock=clock)
    service.register("echo", lambda payload: {"ok": True})
    service.start()
    try:
        task = service.submit(
            CreateTaskRequest(task_type="echo", payload={}, defer_off_peak=True)
        )
        # 高峰时段：任务应保持排队
        import time

        time.sleep(0.2)
        assert service.get(task["task_id"])["status"] == PENDING

        # 推进到夜间闲时，等待工作线程执行
        clock.current = datetime(2026, 10, 5, 23, 30)
        done = service.wait(task["task_id"], timeout=3.0)
        assert done["status"] == SUCCEEDED
    finally:
        service.shutdown()


def test_list_and_filter(tmp_path):
    """按类型与状态过滤任务列表。"""
    service = _service(tmp_path)
    service.register("echo", lambda payload: {"ok": True})
    service.start()
    try:
        service.submit(CreateTaskRequest(task_type="echo", payload={"n": 1}))
        service.submit(CreateTaskRequest(task_type="echo", payload={"n": 2}))
        # 等待执行完成
        import time

        for _ in range(50):
            if service.list_tasks(status=SUCCEEDED)["total"] == 2:
                break
            time.sleep(0.05)
        listing = service.list_tasks(task_type="echo", status=SUCCEEDED)
        assert listing["total"] == 2
        assert service.list_tasks(task_type="other")["total"] == 0
    finally:
        service.shutdown()


def test_streaming_handler_records_reasoning(tmp_path):
    """双参数处理器可上报思考与正文增量，任务收尾时落盘。"""
    service = _service(tmp_path)

    def handler(payload, progress):
        progress({"type": "reasoning", "text": "先看题目。"})
        progress({"type": "reasoning", "text": "再给结论。"})
        progress({"type": "content", "text": "正文内容"})
        return {"ok": True}

    service.register("stream", handler)
    service.start()
    try:
        task = service.submit(CreateTaskRequest(task_type="stream", payload={}))
        done = service.wait(task["task_id"])
        assert done["status"] == SUCCEEDED
        assert done["reasoning"] == "先看题目。再给结论。"
        assert done["stream_content"] == "正文内容"
    finally:
        service.shutdown()


def test_record_stream_records_progress(tmp_path):
    """HTTP 流式接口的任务记录也保存思考与正文增量。"""
    service = _service(tmp_path)
    events = iter(
        [
            {"type": "reasoning", "text": "思考"},
            {"type": "content", "text": "输出"},
            {"type": "done", "resource_id": "r_1"},
        ]
    )
    list(record_stream(service, "forge.generate", {}, events))

    task = service.list_tasks()["items"][0]
    assert task["status"] == SUCCEEDED
    assert task["reasoning"] == "思考"
    assert task["stream_content"] == "输出"


def test_external_task_lifecycle(tmp_path):
    """HTTP 外部任务登记后可手动推进 running/succeeded/failed。"""
    service = _service(tmp_path)
    try:
        task = service.create_external("forge.generate", {"topic": "认识四季"})
        assert task["status"] == PENDING

        service.mark_running(task["task_id"])
        running = service.get(task["task_id"])
        assert running["status"] == "running"
        assert running["attempts"] == 1
        assert running["started_at"]

        service.mark_succeeded(task["task_id"], {"resource_id": "r_1"})
        done = service.get(task["task_id"])
        assert done["status"] == SUCCEEDED
        assert done["result"] == {"resource_id": "r_1"}
        assert done["finished_at"]

        failed_task = service.create_external("forge.generate", {})
        service.mark_running(failed_task["task_id"])
        service.mark_failed(failed_task["task_id"], "boom")
        failed = service.get(failed_task["task_id"])
        assert failed["status"] == FAILED
        assert "boom" in failed["error"]
    finally:
        service.shutdown()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
