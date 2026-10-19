"""存储层测试：增删查、跨实例持久化与条件过滤。"""

import pytest

from kaleido.common.errors import NotFoundError
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService


def _service(tmp_path) -> ProfileService:
    return ProfileService(repository=StudentRepository(tmp_path))


def _create(service: ProfileService, name: str = "测试") -> dict:
    return service.create_student(
        CreateStudentRequest(
            name=name,
            attributes=StudentAttributesInput(
                disability="visual",
                severity="mild",
                cognitive_level="primary_low",
                learning_pace="slow",
            ),
        )
    )


def test_save_get_delete(tmp_path):
    service = _service(tmp_path)
    created = _create(service)
    profile_id = created["profile_id"]
    repository = service.repository

    loaded = repository.get(profile_id)
    assert loaded.name == "测试"

    items, total = repository.list()
    assert total == 1
    assert items[0]["profile_id"] == profile_id

    repository.delete(profile_id)
    with pytest.raises(NotFoundError):
        repository.get(profile_id)


def test_persistence_across_instances(tmp_path):
    service = _service(tmp_path)
    created = _create(service, "持久化")
    reloaded = StudentRepository(tmp_path)
    assert reloaded.get(created["profile_id"]).name == "持久化"


def test_list_filter(tmp_path):
    service = _service(tmp_path)
    _create(service, "A")
    service.create_student(
        CreateStudentRequest(
            name="B",
            attributes=StudentAttributesInput(
                disability="autism",
                severity="moderate",
                cognitive_level="preschool",
                learning_pace="slow",
            ),
        )
    )
    items, total = service.repository.list(disability="autism")
    assert total == 1
    assert items[0]["name"] == "B"
