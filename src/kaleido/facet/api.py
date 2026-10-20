"""facet HTTP API（Bottle）。"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.facet.models import FacetEvaluationRequest
from kaleido.facet.service import FacetService

_logger = get_logger("facet.api")


def create_app(service: FacetService | None = None) -> Bottle:
    """构建 facet 的 Bottle 应用。"""
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
        """校验资源并返回质量报告。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.evaluate(resource_id, FacetEvaluationRequest(**payload))

        return run(action, status=201)

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
