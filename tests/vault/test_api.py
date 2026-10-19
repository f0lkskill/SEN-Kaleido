"""vault REST 接口测试：通过 WSGI 直接调用路由。"""

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

from kaleido.vault.api import create_app
from kaleido.vault.vault import Vault


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
    return _client(create_app(Vault(data_dir=tmp_path)))


def test_create_get_list_delete(tmp_path):
    call = _setup(tmp_path)
    status, body = call("POST", "/api/v1/vault/docs", {"a": 1})
    assert status.startswith("201")
    doc_id = body["data"]["id"]
    assert doc_id == "d_0001"

    status, body = call("GET", f"/api/v1/vault/docs/{doc_id}")
    assert status.startswith("200")
    assert body["data"] == {"a": 1}

    status, body = call("GET", "/api/v1/vault/docs", query="page=1&size=10")
    assert body["data"]["total"] == 1

    status, body = call("DELETE", f"/api/v1/vault/docs/{doc_id}")
    assert status.startswith("200")


def test_update_and_missing(tmp_path):
    call = _setup(tmp_path)
    _, body = call("POST", "/api/v1/vault/docs", {"a": 1})
    doc_id = body["data"]["id"]

    status, body = call("PUT", f"/api/v1/vault/docs/{doc_id}", {"a": 2})
    assert status.startswith("200")

    status, body = call("GET", f"/api/v1/vault/docs/{doc_id}")
    assert body["data"] == {"a": 2}

    status, body = call("GET", "/api/v1/vault/docs/d_9999")
    assert status.startswith("404")
    assert body["code"] == 1002


def test_idempotency_conflict(tmp_path):
    call = _setup(tmp_path)
    # students 集合启用了幂等（docs 未配置，默认关闭），用其验证冲突
    status, _ = call(
        "POST", "/api/v1/vault/students", {"name": "x"}, query="client_request_id=r1"
    )
    assert status.startswith("201")
    status, body = call(
        "POST", "/api/v1/vault/students", {"name": "x"}, query="client_request_id=r1"
    )
    assert status.startswith("409")
    assert body["code"] == 1003


def test_students_namespace_uses_config(tmp_path):
    call = _setup(tmp_path)
    status, body = call(
        "POST",
        "/api/v1/vault/students",
        {
            "name": "小明",
            "attributes": {
                "disabilities": ["visual"],
                "severity": "mild",
                "cognitive_level": "primary_low",
            },
        },
    )
    assert status.startswith("201")
    assert body["data"]["id"] == "p_0001"

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
