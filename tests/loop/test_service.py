"""loop 评价快照服务测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.evidence.models import CreateEvidenceRequest, ReviewEvidenceRequest
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.loop.service import LoopService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _setup(tmp_path):
    vault = Vault(data_dir=tmp_path)
    students = StudentRepository(vault=vault)
    profile_service = ProfileService(repository=students)
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
        student_repository=students,
    )
    loop_service = LoopService(
        profile_service=profile_service,
        evidence_repository=EvidenceRepository(vault=vault),
        vault=vault,
    )
    return profile_service, student, evidence_service, loop_service


def _verified(service, student_id, observation_key, source_type, **extra):
    """新增并审核一条证据。"""
    record = service.create(
        CreateEvidenceRequest(
            student_id=student_id,
            observation_key=observation_key,
            source_type=source_type,
            media_type="text",
            content="课堂记录",
            **extra,
        )
    )
    service.review(
        record["evidence_id"],
        ReviewEvidenceRequest(status="verified", verified_by="教师"),
    )
    return record


def test_snapshot_aggregates_verified_evidence(tmp_path):
    _, student, evidence_service, loop_service = _setup(tmp_path)
    student_id = student["profile_id"]
    _verified(
        evidence_service,
        student_id,
        "class_engagement",
        "classroom_observation",
        level=4,
    )
    _verified(
        evidence_service,
        student_id,
        "practice_completion",
        "work_sample",
        value=80,
    )

    snapshot = loop_service.evaluate_student(student_id)

    assert snapshot["status"] == "ok"
    assert snapshot["coverage"] == 1.0
    assert snapshot["dimension_scores"] == {"participation": 1.0, "practice": 0.8}
    assert snapshot["overall_score"] == 0.89
    assert snapshot["evidence_count"] == 2
    assert snapshot["scored_evidence_count"] == 2
    assert snapshot["missing_observations"] == []

    latest = loop_service.latest(student_id)
    assert latest["snapshot_id"] == snapshot["snapshot_id"]
    assert loop_service.list_snapshots(student_id)["total"] == 1


def test_snapshot_marks_partial_coverage(tmp_path):
    _, student, evidence_service, loop_service = _setup(tmp_path)
    student_id = student["profile_id"]
    _verified(
        evidence_service,
        student_id,
        "class_engagement",
        "classroom_observation",
        level=3,
    )

    snapshot = loop_service.evaluate_student(student_id)

    assert snapshot["status"] == "partial"
    assert snapshot["coverage"] == 0.5
    assert snapshot["dimension_scores"] == {"participation": 0.75}
    assert snapshot["missing_observations"] == ["practice_completion"]


def test_snapshot_without_evidence_is_insufficient(tmp_path):
    _, student, _, loop_service = _setup(tmp_path)

    snapshot = loop_service.evaluate_student(student["profile_id"])

    assert snapshot["status"] == "insufficient"
    assert snapshot["coverage"] == 0.0
    assert snapshot["dimension_scores"] == {}
    assert snapshot["overall_score"] is None
    assert set(snapshot["missing_observations"]) == {
        "class_engagement",
        "practice_completion",
    }
