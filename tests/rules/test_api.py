"""规则集 API 测试：列表、审核与删除。"""

import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.rules.api import create_app
from kaleido.rules.service import PromptRuleService
from kaleido.vault import Vault


def _call(app, method, path, body=None):
    payload = b""
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": "",
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
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    if hasattr(chunks, "close"):
        chunks.close()
    data = json.loads(raw.decode("utf-8")) if raw else {}
    return captured["status"], data


def test_rules_api_flow(tmp_path):
    service = PromptRuleService(vault=Vault(data_dir=tmp_path))
    added = service.add_rules("visual", ["规则一"], source_topic="主题")
    rule_id = added[0]["rule_id"]
    app = create_app(service)

    status, body = _call(app, "GET", "/api/v1/prompt-rules")
    assert status.startswith("200")
    assert body["data"]["total"] == 1

    status, body = _call(
        app,
        "PATCH",
        f"/api/v1/prompt-rules/{rule_id}",
        {"status": "approved"},
    )
    assert status.startswith("200")
    assert body["data"]["status"] == "approved"

    status, body = _call(app, "DELETE", f"/api/v1/prompt-rules/{rule_id}")
    assert status.startswith("200")
    assert body["data"]["rule_id"] == rule_id
    assert service.list_rules()["total"] == 0
