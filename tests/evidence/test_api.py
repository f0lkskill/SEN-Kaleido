"""证据 API 测试：上传附件、文件访问与公有证据归类。"""

import json
import sys
from io import BytesIO
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.evidence.api import create_app as create_evidence_app
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _call(app, method, path, body=b"", content_type="application/json"):
    """调用 WSGI 应用，返回 (状态行, 原始响应, 响应头)。"""
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(body),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    if hasattr(chunks, "close"):
        chunks.close()
    return captured["status"], raw, captured["headers"]


def _setup(tmp_path, monkeypatch):
    """建立临时证据服务，并把上传目录指向临时路径。"""
    media_dir = tmp_path / "evidence_files"
    monkeypatch.setattr("kaleido.evidence.api.EVIDENCE_MEDIA_DIR", media_dir)
    vault = Vault(tmp_path)
    profile_service = ProfileService(repository=StudentRepository(vault=vault))
    student = profile_service.create_student(
        CreateStudentRequest(
            name="小明",
            attributes=StudentAttributesInput(
                disabilities=["visual"],
                severity="moderate",
                cognitive_level="primary_3",
                learning_pace="medium",
                rehab_goals=["language"],
            ),
        )
    )
    service = EvidenceService(
        repository=EvidenceRepository(vault=vault),
        student_repository=StudentRepository(vault=vault),
    )
    return create_evidence_app(service), student


def _multipart(field, filename, content, content_type="application/octet-stream"):
    """构造单个文件的 multipart/form-data 请求体。"""
    boundary = "----kaleido-test-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body += content
    body += f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def test_upload_and_serve_image(tmp_path, monkeypatch):
    app, _student = _setup(tmp_path, monkeypatch)
    content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    body, content_type = _multipart("file", "sample.svg", content, "image/svg+xml")

    status, raw, _headers = _call(app, "POST", "/api/v1/evidence/upload", body, content_type)
    assert status.startswith("201")
    data = json.loads(raw.decode("utf-8"))["data"]
    assert data["media_type"] == "image"
    assert data["url"].startswith("/api/v1/evidence/files/")

    status, served, headers = _call(app, "GET", data["url"])
    assert status.startswith("200")
    assert served == content
    assert "image/svg+xml" in headers.get("Content-Type", "")


def test_upload_rejects_unknown_suffix(tmp_path, monkeypatch):
    app, _student = _setup(tmp_path, monkeypatch)
    body, content_type = _multipart("file", "note.exe", b"binary")

    status, raw, _headers = _call(app, "POST", "/api/v1/evidence/upload", body, content_type)
    assert status.startswith("400")
    assert json.loads(raw.decode("utf-8"))["code"] == 1001


def test_create_public_evidence_then_classify(tmp_path, monkeypatch):
    app, student = _setup(tmp_path, monkeypatch)
    payload = json.dumps(
        {
            "scope": "public",
            "source_type": "classroom_observation",
            "content": "课间主动帮助同伴整理教具。",
        }
    ).encode("utf-8")
    status, raw, _headers = _call(app, "POST", "/api/v1/evidence", payload)
    assert status.startswith("201")
    record = json.loads(raw.decode("utf-8"))["data"]
    assert record["scope"] == "public"

    payload = json.dumps(
        {
            "student_id": student["profile_id"],
            "observation_key": "class_engagement",
        }
    ).encode("utf-8")
    status, raw, _headers = _call(
        app,
        "POST",
        f"/api/v1/evidence/{record['evidence_id']}/classify",
        payload,
    )
    assert status.startswith("200")
    classified = json.loads(raw.decode("utf-8"))["data"]
    assert classified["scope"] == "classified"
    assert classified["student_id"] == student["profile_id"]
