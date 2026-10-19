"""tasks REST 接口测试：通过 WSGI 直接调用路由。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json
import sys
import time
from collections.abc import Callable
from io import BytesIO
from typing import Any

from kaleido.tasks.api import create_app
from kaleido.tasks.service import SUCCEEDED, TaskService
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
    """构建使用临时目录的服务与客户端，注册 echo 处理器。"""
    vault = Vault(data_dir=tmp_path)
    service = TaskService(
        vault=vault,
        config={"worker_count": 1, "schedule": {"defer_poll_seconds": 0.05, "off_peak": {}}},
        autostart=False,
    )
    service.register("echo", lambda payload: {"echo": payload})
    service.start()
    app = create_app(service)
    return service, _client(app)


def test_submit_and_fetch(tmp_path):
    service, call = _setup(tmp_path)
    try:
        status, body = call(
            "POST", "/api/v1/tasks", {"task_type": "echo", "payload": {"value": 7}}
        )
        assert status.startswith("201"), body
        task_id = body["data"]["task_id"]

        # 等待执行完成
        for _ in range(50):
            status, body = call("GET", f"/api/v1/tasks/{task_id}")
            if body["data"]["status"] == SUCCEEDED:
                break
            time.sleep(0.05)
        assert body["data"]["result"] == {"echo": {"value": 7}}

        status, body = call("GET", "/api/v1/tasks", query="task_type=echo")
        assert body["data"]["total"] == 1
    finally:
        service.shutdown()


def test_unknown_type_returns_400(tmp_path):
    service, call = _setup(tmp_path)
    try:
        status, body = call("POST", "/api/v1/tasks", {"task_type": "missing"})
        assert status.startswith("400")
        assert body["code"] == 1001
    finally:
        service.shutdown()


def test_task_types(tmp_path):
    service, call = _setup(tmp_path)
    try:
        status, body = call("GET", "/api/v1/tasks/types")
        assert status.startswith("200")
        assert "echo" in body["data"]["task_types"]
    finally:
        service.shutdown()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
