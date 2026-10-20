"""loop REST 接口测试。"""

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

from kaleido.evidence.models import CreateEvidenceRequest, ReviewEvidenceRequest
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.loop.api import create_app
from kaleido.loop.service import LoopService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.tasks.service import SUCCEEDED, TaskService
from kaleido.vault import Vault


def _client(app: Any) -> Callable[..., tuple[str, dict[str, Any]]]:
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
    students = StudentRepository(vault=vault)
    profile_service = ProfileService(repository=students)
    student = profile_service.create_student(
        CreateStudentRequest(
            name="小明",
            attributes=StudentAttributesInput(
                disabilities=["hearing"],
                severity="mild",
                cognitive_level="primary_5",
                learning_pace="medium",
                rehab_goals=["social"],
            ),
        )
    )
    evidence_service = EvidenceService(
        repository=EvidenceRepository(vault=vault),
        student_repository=students,
    )
    record = evidence_service.create(
        CreateEvidenceRequest(
            student_id=student["profile_id"],
            observation_key="class_engagement",
            source_type="classroom_observation",
            media_type="text",
            content="课堂中主动参与。",
            level=4,
        )
    )
    evidence_service.review(
        record["evidence_id"],
        ReviewEvidenceRequest(status="verified", verified_by="教师"),
    )
    loop_service = LoopService(
        profile_service=profile_service,
        evidence_repository=EvidenceRepository(vault=vault),
        vault=vault,
    )
    task_service = TaskService(
        vault=vault,
        config={"worker_count": 1, "schedule": {}},
        autostart=False,
    )
    app = create_app(loop_service, task_service=task_service)
    return _client(app), student["profile_id"], task_service


def test_manual_evaluate_records_task(tmp_path):
    call, student_id, tasks = _setup(tmp_path)
    status, body = call("POST", f"/api/v1/loop/students/{student_id}/evaluate", {})
    assert status.startswith("201")
    data = body["data"]
    assert data["student_id"] == student_id
    assert data["status"] == "partial"
    assert data["dimension_scores"]["participation"] == 1.0

    items = tasks.list_tasks(task_type="loop.evaluate")["items"]
    assert len(items) == 1
    assert items[0]["status"] == SUCCEEDED
    assert items[0]["result"]["snapshot_id"] == data["snapshot_id"]


def test_latest_snapshot(tmp_path):
    call, student_id, _ = _setup(tmp_path)
    status, body = call("GET", f"/api/v1/loop/students/{student_id}/latest")
    assert status.startswith("404")
    assert body["code"] == 1002

    call("POST", f"/api/v1/loop/students/{student_id}/evaluate", {})
    status, body = call("GET", f"/api/v1/loop/students/{student_id}/latest")
    assert status.startswith("200")
    assert body["data"]["student_id"] == student_id
