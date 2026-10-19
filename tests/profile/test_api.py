"""API 层测试：通过 WSGI 直接调用路由，覆盖成功与错误路径。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json
import sys
from io import BytesIO
from typing import Any, Callable

from kaleido.profile.api import create_app
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService


def _client(app: Any) -> Callable[..., tuple[str, dict[str, Any]]]:
    """把 WSGI 应用包装成简单的 (method, path, body) 调用器，返回 (状态行, 响应体)。"""

    def call(
        method: str, path: str, body: Any = None, query: str = ""
    ) -> tuple[str, dict[str, Any]]:
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "SCRIPT_NAME": "",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(payload),
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        captured: dict[str, str] = {}

        def start_response(status: str, headers: Any, exc_info: Any = None) -> None:
            captured["status"] = status

        chunks = app(environ, start_response)
        raw = b"".join(chunks)
        if hasattr(chunks, "close"):
            chunks.close()
        # 始终返回 dict，避免下游下标时被类型检查判为 Optional
        data: dict[str, Any] = json.loads(raw.decode("utf-8")) if raw else {}
        return captured["status"], data

    return call


def _setup(tmp_path):
    service = ProfileService(repository=StudentRepository(tmp_path))
    return _client(create_app(service))


def _payload(name="小明"):
    return {
        "name": name,
        "attributes": {
            "disability": "visual",
            "severity": "moderate",
            "cognitive_level": "primary_low",
            "rehab_goals": ["language"],
            "learning_pace": "slow",
        },
    }


def test_health(tmp_path):
    call = _setup(tmp_path)
    status, body = call("GET", "/api/v1/health")
    assert status.startswith("200")
    assert body["data"]["status"] == "up"


def test_create_and_get(tmp_path):
    call = _setup(tmp_path)
    status, body = call("POST", "/api/v1/students", _payload())
    assert status.startswith("201")
    assert body["code"] == 0
    profile_id = body["data"]["profile_id"]

    status, body = call("GET", f"/api/v1/students/{profile_id}")
    assert status.startswith("200")
    assert body["data"]["name"] == "小明"


def test_get_missing_returns_404(tmp_path):
    call = _setup(tmp_path)
    status, body = call("GET", "/api/v1/students/p_9999")
    assert status.startswith("404")
    assert body["code"] == 1002


def test_invalid_payload_returns_400(tmp_path):
    call = _setup(tmp_path)
    status, body = call("POST", "/api/v1/students", {"name": "x"})
    assert status.startswith("400")
    assert body["code"] == 1001


def test_list_and_preview_and_meta(tmp_path):
    call = _setup(tmp_path)
    call("POST", "/api/v1/students", _payload())

    status, body = call("GET", "/api/v1/students", query="page=1&size=10")
    assert body["data"]["total"] == 1

    status, body = call(
        "POST",
        "/api/v1/evaluation/framework",
        {
            "disability": "hearing",
            "severity": "mild",
            "cognitive_level": "primary_high",
            "learning_pace": "medium",
        },
    )
    assert body["data"]["framework"]["prompt_template_key"] == "hearing_layer"

    status, body = call("GET", "/api/v1/evaluation/dimensions")
    assert "knowledge" in body["data"]["dimensions"]

    status, body = call("GET", "/api/v1/evaluation/rubric/knowledge")
    assert body["data"]["levels"]

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
