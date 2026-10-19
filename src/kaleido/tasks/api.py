"""kaleido-tasks HTTP API（Bottle）。

统一响应包裹与错误码映射规则与其它模块一致。
"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.tasks.models import CreateTaskRequest
from kaleido.tasks.service import TaskService

_logger = get_logger("tasks.api")


def create_app(service: TaskService | None = None) -> Bottle:
    """构建 tasks 的 Bottle 应用。传入 service 可注入测试用服务。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    svc = service or TaskService()

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
            _logger.exception("tasks 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.get("/api/v1/tasks/types")
    def task_types():
        """返回已注册的任务类型。"""
        return run(lambda: {"task_types": svc.registered_types()})

    @app.post("/api/v1/tasks")
    def create_task():
        """提交异步任务。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.submit(CreateTaskRequest(**payload))

        return run(action, status=201)

    @app.get("/api/v1/tasks")
    def list_tasks():
        """分页列出任务，可按类型/状态过滤。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.list_tasks(
                task_type=query.get("task_type") or None,
                status=query.get("status") or None,
                page=int(query.get("page", 1)),
                size=int(query.get("size", 20)),
            )

        return run(action)

    @app.get("/api/v1/tasks/<task_id>")
    def get_task(task_id):
        """读取单个任务。"""
        return run(lambda: svc.get(task_id))

    @app.delete("/api/v1/tasks/<task_id>")
    def cancel_task(task_id):
        """取消任务。"""
        return run(lambda: svc.cancel(task_id))

    return app


def serve(host: str = "0.0.0.0", port: int = 8083) -> None:
    """用 waitress 启动 tasks 服务（默认端口 8083）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
