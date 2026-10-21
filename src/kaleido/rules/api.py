"""规则集 HTTP API（Bottle）。"""

from typing import Any, cast

from bottle import Bottle, request, response
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError
from kaleido.common.logging import get_logger
from kaleido.common.response import fail, ok
from kaleido.rules.models import PromptRuleUpdateRequest
from kaleido.rules.service import PromptRuleService

_logger = get_logger("rules.api")


def create_app(service: PromptRuleService | None = None) -> Bottle:
    """构建规则集 Bottle 应用。"""
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())
    svc = service or PromptRuleService()

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
            _logger.exception("规则集请求处理失败")
            response.status = 500
            return fail(1000, str(exc))
        response.status = status
        return ok(data)

    @app.get("/api/v1/prompt-rules")
    def list_rules():
        """列出模型沉淀的规则，可按病症与状态筛选。"""
        query = cast("dict[str, str]", request.query)
        return run(
            lambda: svc.list_rules(
                disability=query.get("disability") or None,
                status=query.get("status") or None,
            )
        )

    @app.patch("/api/v1/prompt-rules/<rule_id>")
    def update_rule(rule_id):
        """通过或拒绝规则。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            req = PromptRuleUpdateRequest(**payload)
            return svc.set_status(rule_id, req.status)

        return run(action)

    @app.delete("/api/v1/prompt-rules/<rule_id>")
    def delete_rule(rule_id):
        """删除规则。"""
        return run(lambda: svc.delete_rule(rule_id))

    return app
