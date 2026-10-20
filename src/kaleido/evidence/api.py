"""证据管理 HTTP API 层（Bottle）。

统一约定与其它模块一致：响应包裹、异常映射、依赖注入。
"""

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from bottle import Bottle, abort, request, response, static_file
from pydantic import ValidationError as PydanticValidationError

from kaleido.common.errors import KaleidoError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.common.paths import EVIDENCE_MEDIA_DIR
from kaleido.common.response import fail, ok
from kaleido.evidence.models import (
    MEDIA_IMAGE,
    MEDIA_TEXT,
    MEDIA_VIDEO,
    ClassifyEvidenceRequest,
    CreateEvidenceRequest,
    ReviewEvidenceRequest,
    UpdateEvidenceRequest,
)
from kaleido.evidence.service import EvidenceService

_logger = get_logger("evidence.api")

# 上传文件类型白名单与大小限制
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".ogg", ".mov"}
_TEXT_SUFFIXES = {".txt", ".md"}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _media_type_for_suffix(suffix: str) -> str | None:
    """按扩展名判定媒体类型。"""
    if suffix in _IMAGE_SUFFIXES:
        return MEDIA_IMAGE
    if suffix in _VIDEO_SUFFIXES:
        return MEDIA_VIDEO
    if suffix in _TEXT_SUFFIXES:
        return MEDIA_TEXT
    return None


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
                scope=query.get("scope") or None,
                media_type=query.get("media_type") or None,
                page=int(query.get("page", 1)),
                size=int(query.get("size", 20)),
            )

        return run(action)

    @app.get("/api/v1/evidence/summary")
    def evidence_summary():
        """证据数量汇总。"""

        def action():
            query = cast("dict[str, str]", request.query)
            return svc.summary(
                student_id=query.get("student_id") or None,
                scope=query.get("scope") or None,
            )

        return run(action)

    @app.post("/api/v1/evidence/upload")
    def upload_evidence_file():
        """上传证据附件（文本 / 图像 / 视频）。"""

        def action():
            upload = request.files.get("file")
            if upload is None or not upload.filename:
                raise ValidationError("缺少上传文件")
            original = Path(str(upload.filename).replace("\\", "/")).name
            suffix = Path(original).suffix.lower()
            media_type = _media_type_for_suffix(suffix)
            if media_type is None:
                raise ValidationError("仅支持文本、图像、视频文件")
            try:
                upload.file.seek(0, 2)
                size = upload.file.tell()
                upload.file.seek(0)
            except OSError:
                size = 0
            if size > _MAX_UPLOAD_BYTES:
                raise ValidationError("文件过大，单个文件不能超过 100MB")

            EVIDENCE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            stored = f"{stamp}_{uuid.uuid4().hex[:10]}{suffix}"
            with (EVIDENCE_MEDIA_DIR / stored).open("wb") as handle:
                shutil.copyfileobj(upload.file, handle)
            return {
                "filename": stored,
                "original_name": original,
                "media_type": media_type,
                "size": size,
                "url": f"/api/v1/evidence/files/{stored}",
            }

        return run(action, status=201)

    @app.get("/api/v1/evidence/files/<filename:path>")
    def evidence_file(filename):
        """读取已上传的证据附件（支持视频 Range 请求）。"""
        # 禁止路径穿越，只允许媒体目录下的单层文件名
        if Path(filename).name != filename:
            abort(404, "Not Found")
        response.set_header("Cache-Control", "public, max-age=3600")
        return static_file(filename, root=str(EVIDENCE_MEDIA_DIR))

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

    @app.post("/api/v1/evidence/<evidence_id>/classify")
    def classify_evidence(evidence_id):
        """把公有证据归类到学生与观测点。"""

        def action():
            payload = cast("dict[str, Any]", request.json) or {}
            return svc.classify(evidence_id, ClassifyEvidenceRequest(**payload))

        return run(action)

    @app.delete("/api/v1/evidence/<evidence_id>")
    def delete_evidence(evidence_id):
        """删除证据。"""
        return run(lambda: svc.delete(evidence_id))

    return app
