"""vault 通用 REST 接口（Bottle）。

便于运维、调试与后续模块快速接入；业务模块仍各自暴露领域 API。
统一响应包裹与错误码映射规则与 profile 模块一致。
"""

from typing import Any, cast

from bottle import Bottle, request, response

from kaleido.common.errors import ConflictError, KaleidoError
from kaleido.common.response import fail, ok
from kaleido.vault.vault import Vault


def create_app(vault: Vault | None = None) -> Bottle:
    """构建 vault 的 Bottle 应用。传入 vault 可注入测试用实例。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    store = vault or Vault()

    def run(action, status: int = 200):
        """统一执行包装：异常映射为统一响应并设置状态码。"""
        try:
            data = action()
        except KaleidoError as exc:
            response.status = exc.http_status
            return fail(exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.get("/api/v1/vault/<ns>")
    def list_docs(ns):
        """列出集合内文档，query 传过滤字段与分页。"""

        def action():
            query = cast("dict[str, str]", request.query)
            page = int(query.get("page", 1))
            size = int(query.get("size", 20))
            filters = {
                key: value
                for key, value in query.items()
                if key not in ("page", "size")
            }
            items, total = store.collection(ns).list(filters, page=page, size=size)
            return {"total": total, "page": page, "size": size, "items": items}

        return run(action)

    @app.post("/api/v1/vault/<ns>")
    def create_doc(ns):
        """新建文档，可选 ``client_request_id`` 查询参数用于幂等。"""

        def action():
            collection = store.collection(ns)
            payload = cast("dict[str, Any]", request.json) or {}
            query = cast("dict[str, str]", request.query)
            request_id = query.get("client_request_id") or None
            if request_id and collection.find_by_key(request_id):
                raise ConflictError(f"client_request_id 重复: {request_id}")
            doc_id = collection.next_id()
            collection.put(doc_id, payload, idempotency_key=request_id)
            return {"id": doc_id}

        return run(action, status=201)

    @app.get("/api/v1/vault/<ns>/<doc_id>")
    def get_doc(ns, doc_id):
        """读取文档。"""
        return run(lambda: store.collection(ns).get(doc_id))

    @app.put("/api/v1/vault/<ns>/<doc_id>")
    def update_doc(ns, doc_id):
        """覆盖更新文档。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            store.collection(ns).put(doc_id, payload)
            return {"id": doc_id}

        return run(action)

    @app.delete("/api/v1/vault/<ns>/<doc_id>")
    def delete_doc(ns, doc_id):
        """删除文档。"""
        return run(lambda: (store.collection(ns).delete(doc_id), {"id": doc_id})[1])

    @app.post("/api/v1/vault/<ns>/reindex")
    def reindex(ns):
        """重建集合索引。"""

        def action():
            store.collection(ns).reindex()
            return {"ns": ns}

        return run(action)

    return app


def serve(host: str = "0.0.0.0", port: int = 8081) -> None:
    """用 waitress 启动 vault 服务（默认端口 8081）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
