"""profile 模块 HTTP API 层（Bottle + waitress）。

统一约定：
- 所有路由返回统一响应包裹 :func:`kaleido.common.response.ok` / ``fail``；
- 通过 :func:`create_app` 注入服务，便于测试；
- 业务异常按自身 ``http_status`` 映射状态码，参数校验失败返回 400。
"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.profile.models.evaluation import (
    PromptBoardCreateRequest,
    PromptBoardUpdateRequest,
)
from kaleido.profile.models.student import (
    CreateStudentRequest,
    StudentAttributesInput,
    UpdateStudentRequest,
)
from kaleido.profile.service import ProfileService

_logger = get_logger("profile.api")


def create_app(service: ProfileService | None = None) -> Bottle:
    """构建 Bottle 应用。传入 service 可注入测试用服务。"""
    # bottle 的路由装饰器自带类型标注有缺陷（返回类型含 ModuleType），
    # 这里用 Any 视图规避误报，不影响运行时行为
    app = cast(Any, Bottle())
    svc = service or ProfileService()

    def run(action, status: int = 200):
        """统一执行包装：把异常映射为统一响应，并设置状态码。"""
        try:
            data = action()
        except KaleidoError as exc:
            response.status = exc.http_status
            return fail(exc.code, exc.message)
        except PydanticValidationError as exc:
            # 请求体模型校验失败统一按参数错误处理
            response.status = 400
            return fail(1001, str(exc))
        except Exception as exc:
            # 兜底，避免异常泄漏到 WSGI 层
            _logger.exception("profile 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.get("/api/v1/health")
    def health():
        """健康检查。"""
        return ok({"status": "up"})

    @app.post("/api/v1/students")
    def create_student():
        """建立学生档案。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.create_student(CreateStudentRequest(**payload))

        return run(action, status=201)

    @app.get("/api/v1/students")
    def list_students():
        """分页列出学生档案，可按类型/认知等级过滤。"""

        def action():
            # request.query 被 bottle 标注为 DictProperty，实际是 dict 子类，需 cast
            query = cast("dict[str, str]", request.query)
            page = int(query.get("page", 1))
            size = int(query.get("size", 20))
            return svc.list_students(
                disability=query.get("disability") or None,
                cognitive_level=query.get("cognitive_level") or None,
                page=page,
                size=size,
            )

        return run(action)

    @app.get("/api/v1/students/<profile_id>")
    def get_student(profile_id):
        """获取单个学生档案。"""
        return run(lambda: svc.get_student(profile_id))

    @app.put("/api/v1/students/<profile_id>")
    def update_student(profile_id):
        """更新学生档案。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.update_student(profile_id, UpdateStudentRequest(**payload))

        return run(action)

    @app.delete("/api/v1/students/<profile_id>")
    def delete_student(profile_id):
        """删除学生档案。"""
        return run(lambda: svc.delete_student(profile_id))

    @app.get("/api/v1/students/<profile_id>/prompt-board")
    def get_prompt_board(profile_id):
        """读取画像下方的生成提示词规则板。"""
        return run(lambda: svc.get_prompt_board(profile_id))

    @app.post("/api/v1/students/<profile_id>/prompt-board")
    def add_prompt_board_item(profile_id):
        """手动新增一条生成提示词。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = PromptBoardCreateRequest(**payload)
            return svc.add_prompt_board_item(profile_id, req.text, req.title)

        return run(action, status=201)

    @app.patch("/api/v1/students/<profile_id>/prompt-board/<prompt_id>")
    def update_prompt_board_item(profile_id, prompt_id):
        """修改规则板条目的文本或启用状态。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = PromptBoardUpdateRequest(**payload)
            return svc.update_prompt_board_item(
                profile_id, prompt_id, req.text, req.enabled
            )

        return run(action)

    @app.delete("/api/v1/students/<profile_id>/prompt-board/<prompt_id>")
    def delete_prompt_board_item(profile_id, prompt_id):
        """删除规则板条目。"""
        return run(lambda: svc.delete_prompt_board_item(profile_id, prompt_id))

    @app.get("/api/v1/evaluation/dimensions")
    def dimensions():
        """评价维度定义与基础权重。"""
        return run(svc.get_dimensions)

    @app.get("/api/v1/evaluation/evidence-sources")
    def evidence_sources():
        """证据来源类型定义。"""
        return run(svc.get_evidence_sources)

    @app.get("/api/v1/evaluation/rubric/<key>")
    def rubric(key):
        """指定评分标准。"""
        return run(lambda: svc.get_rubric(key))

    @app.post("/api/v1/evaluation/framework")
    def preview_framework():
        """按给定属性预览评价框架（不落库）。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.preview_framework(StudentAttributesInput(**payload))

        return run(action)

    @app.get("/api/v1/profile/types")
    def profile_types():
        """学生类型定义列表。"""
        return run(svc.list_types)

    @app.post("/api/v1/profile/reload-config")
    def reload_config_route():
        """热重载配置。"""
        return run(svc.reload)

    return app


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """用 waitress 启动生产级 WSGI 服务。"""
    from waitress import serve as waitress_serve

    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
