"""学生画像服务测试：证据汇总、图像输入与画像落库。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import ValidationError
from kaleido.evidence.models import CreateEvidenceRequest
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.forge.llm_client import StubClient
from kaleido.forge.portrait import PortraitService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"kaleido-portrait-test"


def _setup(tmp_path, monkeypatch):
    media_dir = tmp_path / "evidence_files"
    media_dir.mkdir()
    (media_dir / "sample.png").write_bytes(PNG_BYTES)
    monkeypatch.setattr("kaleido.forge.portrait.EVIDENCE_MEDIA_DIR", media_dir)

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
    evidence_service = EvidenceService(
        repository=EvidenceRepository(vault=vault),
        student_repository=StudentRepository(vault=vault),
    )
    evidence_service.create(
        CreateEvidenceRequest(
            student_id=student["profile_id"],
            observation_key="class_engagement",
            source_type="classroom_observation",
            media_type="text",
            content="课堂中主动举手两次，并能回应同伴。",
        )
    )
    evidence_service.create(
        CreateEvidenceRequest(
            student_id=student["profile_id"],
            observation_key="practice_completion",
            source_type="work_sample",
            media_type="image",
            content="练习作品图像。",
            attachments=["/api/v1/evidence/files/sample.png"],
        )
    )

    content = json.dumps(
        {
            "summary": "该生课堂参与主动，练习完成质量较好，仍需加强同伴协作。",
            "strengths": ["主动举手", "能回应同伴"],
            "needs": ["协作机会"],
            "suggestions": ["增加小组活动"],
        },
        ensure_ascii=False,
    )
    client = StubClient(content=content)
    service = PortraitService(
        profile_service=profile_service,
        evidence_repository=EvidenceRepository(vault=vault),
        client=client,
        config={"llm": {"model": "stub"}, "portrait": {}},
    )
    return service, profile_service, student, client


def test_generate_portrait_from_text_and_image(tmp_path, monkeypatch):
    service, profile_service, student, client = _setup(tmp_path, monkeypatch)
    result = service.generate(student["profile_id"])

    portrait = result["portrait"]
    assert portrait["summary"].startswith("该生课堂参与主动")
    assert portrait["evidence_count"] == 2
    assert portrait["image_count"] == 1
    assert portrait["video_count"] == 0

    saved = profile_service.get_student(student["profile_id"])
    assert saved["portrait"]["summary"] == portrait["summary"]
    assert saved["portrait"]["suggestions"] == ["增加小组活动"]

    call = client.calls[0]
    user_content = call["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert any(part.get("type") == "image_url" for part in user_content)
    assert call["response_format"] == {"type": "json_object"}


class _StreamingStub:
    """带流式能力的画像桩：先思考，再输出 JSON。"""

    def __init__(self, content: str):
        self.content = content
        self.model = "stub-stream"
        self.calls: list[dict] = []

    def complete(self, messages, **overrides):  # pragma: no cover
        raise AssertionError("流式路径不应调用 complete")

    def stream(self, messages, **overrides):
        self.calls.append({"messages": messages, **overrides})
        yield {"type": "reasoning", "text": "先看证据。"}
        yield {"type": "content", "text": self.content}


def test_generate_portrait_streams_reasoning(tmp_path, monkeypatch):
    """画像分析通过 on_event 实时上报思考与正文。"""
    service, _profile_service, student, _client = _setup(tmp_path, monkeypatch)
    content = json.dumps(
        {
            "summary": "流式画像",
            "strengths": ["主动参与"],
            "needs": [],
            "suggestions": [],
        },
        ensure_ascii=False,
    )
    service.client = _StreamingStub(content)
    events: list[dict] = []

    result = service.generate(student["profile_id"], on_event=events.append)

    assert any(event["type"] == "reasoning" for event in events)
    assert any(event["type"] == "content" for event in events)
    assert result["portrait"]["summary"] == "流式画像"


def test_generate_portrait_without_evidence_raises(tmp_path, monkeypatch):
    service, _profile_service, student, _client = _setup(tmp_path, monkeypatch)
    # 清空证据后再次生成
    for item in service.evidence.list({"student_id": student["profile_id"]}, page=1, size=100)[0]:
        service.evidence.delete(item["evidence_id"])
    with pytest.raises(ValidationError):
        service.generate(student["profile_id"])
