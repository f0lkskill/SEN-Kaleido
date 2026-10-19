"""本地测试集驱动的 profile 测试。

直接消费 ``tests/fixtures/students/samples.json``，参数化覆盖
「四大类型 × 三种程度」矩阵与边界/非法输入，保证测试数据与联调数据同源。
"""

import pytest

from kaleido.common.errors import ValidationError
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from tests.fixtures import load_student_samples

SAMPLES = load_student_samples()
VALID = SAMPLES["valid"]
EDGE = SAMPLES["edge"]


def _service(tmp_path) -> ProfileService:
    return ProfileService(repository=StudentRepository(tmp_path))


@pytest.mark.parametrize("sample", VALID, ids=[s["id"] for s in VALID])
def test_valid_samples_generate_framework(tmp_path, sample):
    service = _service(tmp_path)
    profile = service.create_student(
        CreateStudentRequest(
            name=sample["name"],
            attributes=StudentAttributesInput(**sample["attributes"]),
        )
    )
    framework = profile["framework"]
    assert framework["indicators"], "评价框架至少包含一个指标"
    assert abs(sum(framework["weights"].values()) - 1.0) < 1e-2
    assert framework["prompt_template_key"].endswith("_layer")


@pytest.mark.parametrize("case", EDGE, ids=[c["id"] for c in EDGE])
def test_edge_cases(tmp_path, case):
    service = _service(tmp_path)
    request = CreateStudentRequest(
        name=case["student"]["name"],
        attributes=StudentAttributesInput(**case["student"]["attributes"]),
    )
    if case["expect"] == "error":
        with pytest.raises(ValidationError):
            service.create_student(request)
        return

    profile = service.create_student(request)
    attributes = profile["attributes"]
    if case["id"] == "default_sensory":
        assert attributes["sensory_preference"] == "audio_first"
    if case["id"] == "explicit_sensory":
        assert attributes["sensory_preference"] == "mixed"
    if case["id"] == "preschool_visual_filter":
        keys = {indicator["key"] for indicator in profile["framework"]["indicators"]}
        assert "braille_literacy" not in keys
