"""forge REST 接口测试：通过 WSGI 直接调用路由。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json
import sys
from collections.abc import Callable
from io import BytesIO
from typing import Any

from kaleido.forge.api import create_app
from kaleido.forge.llm_client import StubClient
from kaleido.forge.service import ForgeService
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _client(app: Any) -> Callable[..., tuple[str, dict[str, Any]]]:
    """把 WSGI 应用包装成 (method, path, body, query) 调用器。"""

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
        data: dict[str, Any] = json.loads(raw.decode("utf-8")) if raw else {}
        return captured["status"], data

    return call


def _setup(tmp_path):
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    service = ForgeService(
        client=StubClient(content="API 生成的资源"),
        profile_service=profile_service,
        vault=Vault(data_dir=tmp_path),
    )
    return _client(create_app(service))


def _payload(**overrides) -> dict:
    data = {
        "attributes": {
            "disabilities": ["visual"],
            "severity": "moderate",
            "cognitive_level": "primary_low",
            "rehab_goals": ["language"],
            "learning_pace": "slow",
        },
        "resource_type": "courseware",
        "topic": "认识四季",
    }
    data.update(overrides)
    return data


def test_generate_and_fetch(tmp_path):
    call = _setup(tmp_path)
    status, body = call("POST", "/api/v1/forge/generate", _payload())
    assert status.startswith("201")
    resource_id = body["data"]["resource_id"]
    assert body["data"]["content"] == "API 生成的资源"

    status, body = call("GET", f"/api/v1/forge/resources/{resource_id}")
    assert status.startswith("200")
    assert body["data"]["content"] == "API 生成的资源"

    status, body = call("GET", "/api/v1/forge/resources", query="resource_type=courseware")
    assert body["data"]["total"] == 1


def test_invalid_request(tmp_path):
    call = _setup(tmp_path)
    status, body = call("POST", "/api/v1/forge/generate", _payload(resource_type="video"))
    assert status.startswith("400")
    assert body["code"] == 1001

    status, body = call(
        "POST", "/api/v1/forge/generate", {"resource_type": "courseware", "topic": "x"}
    )
    assert status.startswith("400")


def test_resource_types(tmp_path):
    call = _setup(tmp_path)
    status, body = call("GET", "/api/v1/forge/resource-types")
    assert status.startswith("200")
    assert "courseware" in body["data"]

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
