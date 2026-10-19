"""forge HTTP API（Bottle）。"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.response import fail, ok
from kaleido.forge.models import GenerateRequest
from kaleido.forge.service import ForgeService


def create_app(service: ForgeService | None = None) -> Bottle:
    """构建 forge 的 Bottle 应用。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    svc = service or ForgeService()

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
        except Exception as exc:  # noqa: BLE001
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.post("/api/v1/forge/generate")
    def generate():
        """生成资源。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.generate(GenerateRequest(**payload))

        return run(action, status=201)

    @app.get("/api/v1/forge/resources")
    def list_resources():
        """分页列出资源。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.list_resources(
                resource_type=query.get("resource_type") or None,
                disability=query.get("disability") or None,
                status=query.get("status") or None,
                page=int(query.get("page", 1)),
                size=int(query.get("size", 20)),
            )

        return run(action)

    @app.get("/api/v1/forge/resources/<resource_id>")
    def get_resource(resource_id):
        """读取单个资源。"""
        return run(lambda: svc.get_resource(resource_id))

    @app.get("/api/v1/forge/resource-types")
    def resource_types():
        """可用资源类型。"""
        return run(svc.resource_types)

    return app


def serve(host: str = "0.0.0.0", port: int = 8082) -> None:
    """用 waitress 启动 forge 服务（默认端口 8082）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
