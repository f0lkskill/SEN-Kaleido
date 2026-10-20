"""证据管理 HTTP API 层（Bottle）。

统一约定与其它模块一致：响应包裹、异常映射、依赖注入。
"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.evidence.models import (
    CreateEvidenceRequest,
    ReviewEvidenceRequest,
    UpdateEvidenceRequest,
)
from kaleido.evidence.service import EvidenceService

_logger = get_logger("evidence.api")


def create_app(service: EvidenceService | None = None) -> Bottle:
    """构建证据 API 应用；可注入测试用服务。"""
    app = cast(Any, Bottle())
    svc = service or EvidenceService()

    def run(action, status: int = 200):
        """统一执行包装：异常映射为响应并设置状态码。"""
        try:
            data = action()
        except KaleidoError as exc:
            response.status = exc.http_status
            return fail(exc.code, exc.message)
        except PydanticValidationError as exc:
            response.status = 400
            return fail(1001, str(exc))
        except Exception as exc:
            _logger.exception("evidence 请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.post("/api/v1/evidence")
    def create_evidence():
        """新增证据草稿。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.create(CreateEvidenceRequest(**payload))

        return run(action, status=201)

    @app.get("/api/v1/evidence")
    def list_evidence():
        """按学生/观测点/来源/状态筛选证据。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.list(
                student_id=query.get("student_id") or None,
                observation_key=query.get("observation_key") or None,
                source_type=query.get("source_type") or None,
                status=query.get("status") or None,
                page=int(query.get("page", 1)),
                size=int(query.get("size", 20)),
            )

        return run(action)

    @app.get("/api/v1/evidence/summary")
    def evidence_summary():
        """证据数量汇总。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.summary(student_id=query.get("student_id") or None)

        return run(action)

    @app.get("/api/v1/evidence/<evidence_id>")
    def get_evidence(evidence_id):
        """读取单条证据。"""
        return run(lambda: svc.get(evidence_id))

    @app.put("/api/v1/evidence/<evidence_id>")
    def update_evidence(evidence_id):
        """更新证据内容。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.update(evidence_id, UpdateEvidenceRequest(**payload))

        return run(action)

    @app.post("/api/v1/evidence/<evidence_id>/review")
    def review_evidence(evidence_id):
        """审核通过或驳回。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.review(evidence_id, ReviewEvidenceRequest(**payload))

        return run(action)

    @app.delete("/api/v1/evidence/<evidence_id>")
    def delete_evidence(evidence_id):
        """删除证据。"""
        return run(lambda: svc.delete(evidence_id))

    return app
