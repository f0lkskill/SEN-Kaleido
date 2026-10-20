"""facet REST 接口测试：通过 WSGI 直接调用路由。"""

import json
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.facet.api import create_app
from kaleido.facet.service import FacetService
from kaleido.forge.llm_client import StubClient
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.tasks.service import FAILED, SUCCEEDED, TaskService
from kaleido.vault import Vault

_LLM_CONTENT = json.dumps(
    {
        "summary": "整体可用。",
        "scores": {
            "disability_fit": 90,
            "cognitive_load": 90,
            "sensory_accessibility": 90,
            "teaching_usability": 90,
        },
        "strengths": ["结构清晰"],
        "issues": [],
        "suggestions": ["保持短句"],
    },
    ensure_ascii=False,
)


def _client(app: Any) -> Callable[..., tuple[str, dict[str, Any]]]:
    """把 WSGI 应用包装成 (method, path, body) 调用器。"""

    def call(method: str, path: str, body: Any = None) -> tuple[str, dict[str, Any]]:
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
    vault = Vault(data_dir=tmp_path)
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    profile = profile_service.create_student(
        CreateStudentRequest(
            name="小明",
            attributes=StudentAttributesInput(
                disabilities=["visual"],
                severity="moderate",
                cognitive_level="primary_3",
                sensory_preference="visual_first",
                learning_pace="slow",
                rehab_goals=["language"],
            ),
        )
    )
    resources = vault.collection("resources")
    resource_id = resources.next_id()
    resources.put(
        resource_id,
        {
            "resource_type": "courseware",
            "topic": "认识春天",
            "profile_id": profile["profile_id"],
            "attributes": profile["attributes"],
            "content": "![春天](spring.png)\n\n春天来了。",
            "status": "draft",
        },
    )
    service = FacetService(
        profile_service=profile_service,
        client=StubClient(content=_LLM_CONTENT),
        vault=vault,
    )
    task_service = TaskService(
        vault=vault,
        config={"worker_count": 1, "schedule": {}},
        autostart=False,
    )
    app = create_app(service, task_service=task_service)
    return _client(app), resource_id, task_service


def test_evaluate_and_get_report(tmp_path):
    call, resource_id, _ = _setup(tmp_path)
    status, body = call("POST", f"/api/v1/facet/resources/{resource_id}/evaluate", {})
    assert status.startswith("201")
    assert body["data"]["verdict"] == "review"
    assert body["data"]["score"] == 90

    status, body = call("GET", f"/api/v1/facet/resources/{resource_id}")
    assert status.startswith("200")
    assert body["data"]["summary"] == "整体可用。"


def test_evaluate_records_task(tmp_path):
    """资源库触发质量校验时，任务面板应能看到对应记录。"""
    call, resource_id, tasks = _setup(tmp_path)
    status, _ = call("POST", f"/api/v1/facet/resources/{resource_id}/evaluate", {})
    assert status.startswith("201")

    items = tasks.list_tasks(task_type="facet.evaluate")["items"]
    assert len(items) == 1
    task = items[0]
    assert task["status"] == SUCCEEDED
    assert task["payload"]["resource_id"] == resource_id
    assert task["result"]["resource_id"] == resource_id
    assert task["result"]["verdict"] == "review"
    assert task["result"]["score"] == 90
    assert task["started_at"] and task["finished_at"]


def test_evaluate_failure_records_task(tmp_path):
    """校验失败时任务也应留痕并标记失败。"""
    call, _, tasks = _setup(tmp_path)
    status, body = call("POST", "/api/v1/facet/resources/r_99999/evaluate", {})
    assert status.startswith("404")
    assert body["code"] == 1002

    items = tasks.list_tasks(task_type="facet.evaluate")["items"]
    assert len(items) == 1
    assert items[0]["status"] == FAILED
    assert items[0]["error"]


def test_missing_report_returns_404(tmp_path):
    call, resource_id, _ = _setup(tmp_path)
    status, body = call("GET", f"/api/v1/facet/resources/{resource_id}")
    assert status.startswith("404")
    assert body["code"] == 1002


def test_unknown_resource_returns_404(tmp_path):
    call, _, _ = _setup(tmp_path)
    status, body = call("POST", "/api/v1/facet/resources/r_99999/evaluate", {})
    assert status.startswith("404")
    assert body["code"] == 1002


def test_config_endpoint(tmp_path):
    call, _, _ = _setup(tmp_path)
    status, body = call("GET", "/api/v1/facet/config")
    assert status.startswith("200")
    assert "disability_fit" in body["data"]["dimensions"]
