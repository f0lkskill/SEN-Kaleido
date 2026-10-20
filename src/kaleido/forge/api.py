"""forge HTTP API（Bottle）。"""

import json
from collections.abc import Iterator
from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.forge.models import GenerateRequest
from kaleido.forge.portrait import PortraitService
from kaleido.forge.service import ForgeService
from kaleido.tasks.service import TaskService

_logger = get_logger("forge.api")


def _task_summary(result: Any) -> dict:
    """提取任务面板需要的精简结果，避免整篇正文塞进任务记录。"""
    if not isinstance(result, dict):
        return {"value": result}
    summary = {
        key: result[key]
        for key in ("resource_id", "profile_id", "model", "status", "prompt_template_key")
        if key in result
    }
    quality = result.get("quality")
    if isinstance(quality, dict):
        summary["quality"] = {
            "ok": quality.get("ok"),
            "score": quality.get("score"),
            "issues": len(quality.get("issues") or []),
        }
    text = result.get("summary")
    if isinstance(text, str) and len(text) <= 200:
        summary["summary"] = text
    return summary or {"keys": sorted(result)}


def _sse(events: Iterator[dict]) -> Iterator[str]:
    """把事件字典序列化为 SSE 文本块（``data: {...}`` + 空行）。"""
    for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(
    service: ForgeService | None = None,
    portrait_service: PortraitService | None = None,
    task_service: TaskService | None = None,
) -> Bottle:
    """构建 forge 的 Bottle 应用。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    svc = service or ForgeService()
    portrait = portrait_service or PortraitService()

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
            _logger.exception("forge 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    def run_recorded(task_type: str, payload: dict, action):
        """把 HTTP 同步生成登记为任务，便于任务面板观察长任务。"""
        if task_service is None:
            return action()
        task = task_service.create_external(task_type, payload)
        task_id = task["task_id"]
        task_service.mark_running(task_id)
        try:
            result = action()
        except Exception as exc:
            task_service.mark_failed(task_id, str(exc))
            raise
        task_service.mark_succeeded(task_id, _task_summary(result))
        return result

    def record_stream(events: Iterator[dict], payload: dict) -> Iterator[dict]:
        """给流式生成套一层任务生命周期记录。"""
        if task_service is None:
            yield from events
            return
        task = task_service.create_external("forge.generate", payload)
        task_id = task["task_id"]
        task_service.mark_running(task_id)
        finished = False
        try:
            for event in events:
                event_type = event.get("type")
                if event_type == "done":
                    task_service.mark_succeeded(task_id, _task_summary(event))
                    finished = True
                elif event_type == "error":
                    task_service.mark_failed(
                        task_id, str(event.get("message") or "生成失败")
                    )
                    finished = True
                yield event
        finally:
            if not finished:
                task_service.mark_failed(task_id, "生成流提前结束或连接中断")

    @app.post("/api/v1/forge/generate")
    def generate():
        """生成资源。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = GenerateRequest(**payload)
            return run_recorded("forge.generate", req.model_dump(), lambda: svc.generate(req))

        return run(action, status=201)

    @app.post("/api/v1/forge/generate/stream")
    def generate_stream():
        """流式生成资源（SSE）：实时返回模型思考与正文增量。"""
        payload = cast("dict[str, Any]", request.json) or {}
        try:
            req = GenerateRequest(**payload)
        except PydanticValidationError as exc:
            response.status = 400
            return fail(1001, str(exc))
        response.content_type = "text/event-stream; charset=utf-8"
        response.set_header("Cache-Control", "no-cache")
        response.set_header("X-Accel-Buffering", "no")
        return _sse(record_stream(svc.generate_stream(req), req.model_dump()))

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

    @app.post("/api/v1/forge/resources/<resource_id>/status")
    def update_resource_status(resource_id):
        """更新资源审核状态（通过/退回）。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.update_resource_status(resource_id, str(payload.get("status", "")))

        return run(action)

    @app.delete("/api/v1/forge/resources/<resource_id>")
    def delete_resource(resource_id):
        """删除资源。"""
        return run(lambda: svc.delete_resource(resource_id))

    @app.get("/api/v1/forge/resource-types")
    def resource_types():
        """可用资源类型。"""
        return run(svc.resource_types)

    @app.post("/api/v1/forge/students/<profile_id>/portrait")
    def generate_portrait(profile_id):
        """分析学生全部证据并生成学情画像。"""
        return run(
            lambda: run_recorded(
                "forge.portrait",
                {"profile_id": profile_id},
                lambda: portrait.generate(profile_id),
            ),
            status=201,
        )

    return app


def serve(host: str = "0.0.0.0", port: int = 8082) -> None:
    """用 waitress 启动 forge 服务（默认端口 8082）。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
