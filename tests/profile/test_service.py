"""服务层测试：建档、幂等、更新重建框架、预览不落库与元数据。"""

import pytest

from kaleido.common.errors import ConflictError
from kaleido.profile.models.student import (
    CreateStudentRequest,
    StudentAttributesInput,
    UpdateStudentRequest,
)
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService


def _service(tmp_path) -> ProfileService:
    return ProfileService(repository=StudentRepository(tmp_path))


def _input(**overrides) -> StudentAttributesInput:
    data = {
        "disability": "visual",
        "severity": "moderate",
        "cognitive_level": "primary_low",
        "rehab_goals": ["language"],
        "learning_pace": "slow",
    }
    data.update(overrides)
    return StudentAttributesInput(**data)


def test_create_returns_framework(tmp_path):
    service = _service(tmp_path)
    result = service.create_student(CreateStudentRequest(name="小明", attributes=_input()))
    assert result["profile_id"] == "p_0001"
    assert result["attributes"]["sensory_preference"] == "audio_first"
    assert result["framework"]["weights"]
    assert result["framework"]["prompt_template_key"] == "visual_layer"


def test_duplicate_request_id_conflict(tmp_path):
    service = _service(tmp_path)
    request = CreateStudentRequest(
        client_request_id="req-1", name="小明", attributes=_input()
    )
    service.create_student(request)
    with pytest.raises(ConflictError):
        service.create_student(request)


def test_update_regenerates_framework(tmp_path):
    service = _service(tmp_path)
    created = service.create_student(CreateStudentRequest(name="小明", attributes=_input()))
    updated = service.update_student(
        created["profile_id"],
        UpdateStudentRequest(
            attributes=_input(disability="autism", severity="severe", rehab_goals=[])
        ),
    )
    assert updated["attributes"]["disability"] == "autism"
    assert updated["framework"]["prompt_template_key"] == "autism_layer"


def test_preview_does_not_persist(tmp_path):
    service = _service(tmp_path)
    service.preview_framework(_input(disability="hearing"))
    assert service.repository.list()[1] == 0


def test_metadata_endpoints(tmp_path):
    service = _service(tmp_path)
    assert "knowledge" in service.get_dimensions()["dimensions"]
    assert service.get_rubric("knowledge")["levels"][0]["label"] == "未达成"
    assert "item_response" in service.get_evidence_sources()
    assert set(service.reload()["student_types"]) == {
        "visual",
        "hearing",
        "intellectual",
        "autism",
    }
