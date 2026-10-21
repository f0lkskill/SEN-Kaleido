"""facet HTTP API（Bottle）。"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.facet.models import FacetEvaluationRequest
from kaleido.facet.service import FacetService
from kaleido.tasks.recording import can_queue, record_task, submit_task
from kaleido.tasks.service import TaskService

_logger = get_logger("facet.api")


def _sync_requested() -> bool:
    """请求是否显式要求同步执行（``?sync=1``）。"""
    query = cast("dict[str, str]", request.query)
    return str(query.get("sync", "")).lower() in {"1", "true", "yes"}


def create_app(
    service: FacetService | None = None,
    task_service: TaskService | None = None,
) -> Bottle:
    """构建 facet 的 Bottle 应用；可注入任务服务以便记录模型分析过程。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    svc = service or FacetService()

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
            _logger.exception("facet 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.post("/api/v1/facet/resources/<resource_id>/evaluate")
    def evaluate(resource_id):
        """校验资源：默认提交后台任务，``?sync=1`` 时同步返回报告。"""
        queued = can_queue(task_service, "facet.evaluate") and not _sync_requested()

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = FacetEvaluationRequest(**payload)
            task_payload = {"resource_id": resource_id, **req.model_dump()}
            if queued:
                return submit_task(task_service, "facet.evaluate", task_payload)
            return record_task(
                task_service,
                "facet.evaluate",
                task_payload,
                lambda: svc.evaluate(resource_id, req),
            )

        return run(action, status=202 if queued else 201)

    @app.get("/api/v1/facet/resources/<resource_id>")
    def get_report(resource_id):
        """读取资源最近一次质量报告。"""
        return run(lambda: svc.get_report(resource_id))

    @app.get("/api/v1/facet/config")
    def config_summary():
        """评分维度、权重与阈值。"""
        return run(svc.config_summary)

    return app


def serve(host: str = "0.0.0.0", port: int = 8083) -> None:
    """用 waitress 启动 facet 服务（默认端口 8083）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
