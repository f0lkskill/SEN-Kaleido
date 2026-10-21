"""任务恢复测试：进程重启后未完成任务重新入队，不永久悬挂。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.tasks.models import CreateTaskRequest
from kaleido.tasks.service import (
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    TaskService,
)
from kaleido.vault import Vault


def _service(tmp_path, config=None):
    """构建不自动启动的工作服务。"""
    base_config = {"worker_count": 1, "max_recoveries": 2, "schedule": {}}
    if config:
        base_config.update(config)
    return TaskService(
        vault=Vault(data_dir=tmp_path),
        config=base_config,
        autostart=False,
    )


def _mark_running(service, task_id, attempts=1, recoveries=0):
    """把任务文档改为执行中，模拟上次进程中断。"""
    document = service.get(task_id)
    document["status"] = RUNNING
    document["attempts"] = attempts
    document["recoveries"] = recoveries
    document["started_at"] = document.get("created_at")
    service.tasks.put(task_id, document)


def test_recover_pending_and_running(tmp_path):
    """pending 与中断的 running 任务都会重新执行。"""
    first = _service(tmp_path)
    first.register("echo", lambda payload: {"echo": payload.get("value")})
    pending = first.submit(CreateTaskRequest(task_type="echo", payload={"value": "p"}))
    running = first.submit(CreateTaskRequest(task_type="echo", payload={"value": "r"}))
    _mark_running(first, running["task_id"])

    second = _service(tmp_path)
    second.register("echo", lambda payload: {"echo": payload.get("value")})
    stats = second.recover()
    assert stats == {"requeued": 2, "failed": 0, "skipped": 0}

    second.start()
    try:
        done_pending = second.wait(pending["task_id"], timeout=3.0)
        done_running = second.wait(running["task_id"], timeout=3.0)
        assert done_pending["status"] == SUCCEEDED
        assert done_running["status"] == SUCCEEDED
        assert done_running["result"] == {"echo": "r"}
        assert done_running["recoveries"] == 1
        assert done_running["attempts"] == 1
    finally:
        second.shutdown()


def test_recover_running_exceeds_limit(tmp_path):
    """超过恢复上限的中断任务标记失败，避免无限重启。"""
    service = _service(tmp_path, {"max_recoveries": 1})
    service.register("echo", lambda payload: {"ok": True})
    task = service.submit(CreateTaskRequest(task_type="echo", payload={}))
    _mark_running(service, task["task_id"], recoveries=1)

    stats = service.recover()

    assert stats["failed"] == 1
    document = service.get(task["task_id"])
    assert document["status"] == FAILED
    assert "恢复上限" in (document["error"] or "")


def test_recover_skips_unregistered_type(tmp_path):
    """处理器尚未注册时保持任务原状，等待注册后再恢复。"""
    first = _service(tmp_path)
    first.register("later", lambda payload: {"ok": True})
    task = first.submit(CreateTaskRequest(task_type="later", payload={}))

    second = _service(tmp_path)
    stats = second.recover()

    assert stats == {"requeued": 0, "failed": 0, "skipped": 1}
    assert second.get(task["task_id"])["status"] == PENDING
