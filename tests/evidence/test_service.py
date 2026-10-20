"""证据服务测试：落库校验、审核流转、筛选与统计。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import ValidationError
from kaleido.evidence.models import (
    ClassifyEvidenceRequest,
    CreateEvidenceRequest,
    ReviewEvidenceRequest,
    UpdateEvidenceRequest,
)
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _setup(tmp_path):
    """建立共享 vault 的学生档案与证据服务。"""
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
    return student, service


def _request(student, **overrides):
    """构造一条默认合法的证据请求。"""
    data = {
        "student_id": student["profile_id"],
        "observation_key": "class_engagement",
        "source_type": "classroom_observation",
        "content": "小组活动中主动举手两次。",
        "collector": "王老师",
    }
    data.update(overrides)
    return CreateEvidenceRequest(**data)


def test_create_evidence_as_draft(tmp_path):
    student, service = _setup(tmp_path)
    record = service.create(_request(student))
    assert record["evidence_id"] == "e_00001"
    assert record["status"] == "draft"
    assert record["title"] == "课堂参与程度"
    assert record["collected_at"]


def test_unknown_source_rejected(tmp_path):
    student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(_request(student, source_type="unknown"))


def test_unknown_observation_rejected(tmp_path):
    student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(_request(student, observation_key="not_exists"))


def test_source_not_declared_by_observation_rejected(tmp_path):
    student, service = _setup(tmp_path)
    # 课堂参与只接受课堂观察/教师评分，不接受作品样本
    with pytest.raises(ValidationError):
        service.create(_request(student, source_type="work_sample"))


def test_unknown_student_rejected(tmp_path):
    _student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(_request({"profile_id": "p_9999"}))


def test_review_flow(tmp_path):
    student, service = _setup(tmp_path)
    record = service.create(_request(student))
    reviewed = service.review(
        record["evidence_id"],
        ReviewEvidenceRequest(status="verified", verified_by="李老师"),
    )
    assert reviewed["status"] == "verified"
    assert reviewed["verified_by"] == "李老师"
    assert reviewed["verified_at"]


def test_review_rejects_invalid_status(tmp_path):
    student, service = _setup(tmp_path)
    record = service.create(_request(student))
    with pytest.raises(ValidationError):
        service.review(record["evidence_id"], ReviewEvidenceRequest(status="draft"))


def test_verified_evidence_cannot_be_updated(tmp_path):
    student, service = _setup(tmp_path)
    record = service.create(_request(student))
    service.review(
        record["evidence_id"],
        ReviewEvidenceRequest(status="verified", verified_by="李老师"),
    )
    with pytest.raises(ValidationError):
        service.update(record["evidence_id"], UpdateEvidenceRequest(content="改内容"))


def test_list_filters_and_summary(tmp_path):
    student, service = _setup(tmp_path)
    first = service.create(_request(student))
    service.create(_request(student, source_type="teacher_rating", content="评分 3 级"))
    service.review(
        first["evidence_id"],
        ReviewEvidenceRequest(status="verified", verified_by="李老师"),
    )

    listing = service.list(student_id=student["profile_id"], status="verified")
    assert listing["total"] == 1
    assert listing["items"][0]["evidence_id"] == first["evidence_id"]

    summary = service.summary(student_id=student["profile_id"])
    assert summary["total"] == 2
    assert summary["by_status"]["verified"] == 1
    assert summary["by_status"]["draft"] == 1
    assert summary["by_source"]["classroom_observation"] == 1
    assert summary["by_source"]["teacher_rating"] == 1


def test_create_public_evidence_without_owner(tmp_path):
    _student, service = _setup(tmp_path)
    record = service.create(
        CreateEvidenceRequest(
            scope="public",
            source_type="classroom_observation",
            content="走廊观察：学生主动向同伴问好。",
        )
    )
    assert record["scope"] == "public"
    assert record["student_id"] == ""
    assert record["observation_key"] == ""
    assert record["media_type"] == "text"

    listing = service.list(scope="public")
    assert listing["total"] == 1
    summary = service.summary()
    assert summary["by_scope"]["public"] == 1
    assert summary["by_scope"]["classified"] == 0


def test_public_evidence_rejects_owner(tmp_path):
    student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(
            CreateEvidenceRequest(
                scope="public",
                student_id=student["profile_id"],
                source_type="classroom_observation",
                content="不应关联学生",
            )
        )


def test_classified_evidence_requires_student_and_observation(tmp_path):
    _student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(
            CreateEvidenceRequest(
                scope="classified",
                source_type="classroom_observation",
                content="缺少学生与观测点",
            )
        )


def test_image_evidence_requires_attachment(tmp_path):
    _student, service = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.create(
            CreateEvidenceRequest(
                scope="public",
                source_type="image_capture",
                media_type="image",
                content="学生绘画作品",
            )
        )

    record = service.create(
        CreateEvidenceRequest(
            scope="public",
            source_type="image_capture",
            media_type="image",
            content="学生绘画作品",
            attachments=["/assets/samples/sample_evidence_image.svg"],
        )
    )
    assert record["media_type"] == "image"
    listing = service.list(media_type="image")
    assert listing["total"] == 1


def test_classify_public_evidence(tmp_path):
    student, service = _setup(tmp_path)
    record = service.create(
        CreateEvidenceRequest(
            scope="public",
            source_type="classroom_observation",
            content="课堂中主动举手两次。",
        )
    )
    classified = service.classify(
        record["evidence_id"],
        ClassifyEvidenceRequest(
            student_id=student["profile_id"],
            observation_key="class_engagement",
        ),
    )
    assert classified["scope"] == "classified"
    assert classified["student_id"] == student["profile_id"]
    assert classified["observation_key"] == "class_engagement"
    assert classified["title"] == "课堂参与程度"

    summary = service.summary()
    assert summary["by_scope"]["public"] == 0
    assert summary["by_scope"]["classified"] == 1

