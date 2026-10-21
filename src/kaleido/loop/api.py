"""loop HTTP API（Bottle）。

评价快照计算是可追溯的后台动作：通过 HTTP 手动触发时同步返回结果，
同时写入任务面板；证据审核通过后由统一入口自动投递 loop.evaluate 任务。
"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.loop.models import LoopEvaluateRequest
from kaleido.loop.service import LoopService
from kaleido.tasks.recording import can_queue, record_task, submit_task
from kaleido.tasks.service import TaskService

_logger = get_logger("loop.api")


def _sync_requested() -> bool:
    """请求是否显式要求同步执行（``?sync=1``）。"""
    query = cast("dict[str, str]", request.query)
    return str(query.get("sync", "")).lower() in {"1", "true", "yes"}


def create_app(
    service: LoopService | None = None,
    task_service: TaskService | None = None,
) -> Bottle:
    """构建 loop 的 Bottle 应用。"""
    app = cast(Any, Bottle())
    svc = service or LoopService()

    def run(action, status: int = 200):
        """统一执行包装：异常映射为统一响应并设置状态码。"""
        try:
            data = action()
        except KaleidoError as exc:
            response.status = exc.http_status
            return fail(exc.code, exc.message)
        except PydanticValidationError as exc:
            response.status = 400
            return fail(1001, str(exc))
        except Exception as exc:
            _logger.exception("loop 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.post("/api/v1/loop/students/<student_id>/evaluate")
    def evaluate_student(student_id):
        """手动触发评价快照：默认入队，``?sync=1`` 时同步计算。"""
        queued = can_queue(task_service, "loop.evaluate") and not _sync_requested()

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = LoopEvaluateRequest(**payload)
            task_payload = {
                "student_id": student_id,
                "trigger": "manual",
                **req.model_dump(),
            }
            if queued:
                return submit_task(task_service, "loop.evaluate", task_payload)
            return record_task(
                task_service,
                "loop.evaluate",
                task_payload,
                lambda: svc.evaluate_student(student_id, req),
            )

        return run(action, status=202 if queued else 201)

    @app.get("/api/v1/loop/students/<student_id>/latest")
    def latest_snapshot(student_id):
        """读取学生最近一次评价快照。"""
        return run(lambda: svc.latest(student_id))

    @app.get("/api/v1/loop/students/<student_id>/snapshots")
    def list_snapshots(student_id):
        """分页列出学生评价快照。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.list_snapshots(
                student_id,
                page=int(query.get("page", 1)),
                size=int(query.get("size", 20)),
            )

        return run(action)

    @app.get("/api/v1/loop/snapshots/<snapshot_id>")
    def get_snapshot(snapshot_id):
        """读取指定评价快照。"""
        return run(lambda: svc.get_snapshot(snapshot_id))

    return app


def serve(host: str = "0.0.0.0", port: int = 8084) -> None:
    """用 waitress 启动 loop 服务（默认端口 8084）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
