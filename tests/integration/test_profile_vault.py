"""profile ↔ vault 对接测试。

验证 ProfileService 通过 StudentRepository（vault 适配器）完成落盘，
且跨实例可恢复、幂等、更新、删除、筛选与索引一致性均正确。
"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json

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


def _attributes(**overrides) -> StudentAttributesInput:
    data = {
        "disabilities": ["visual"],
        "severity": "moderate",
        "cognitive_level": "primary_3",
        "rehab_goals": ["language"],
        "learning_pace": "slow",
    }
    data.update(overrides)
    return StudentAttributesInput(**data)


def test_create_lands_on_disk(tmp_path):
    service = _service(tmp_path)
    created = service.create_student(CreateStudentRequest(name="小明", attributes=_attributes()))

    shard = tmp_path / "students" / "p_0001.json"
    assert shard.exists()
    payload = json.loads(shard.read_text(encoding="utf-8"))
    # envelope=false：分片即业务文档本身
    assert payload["profile_id"] == "p_0001"
    assert payload["name"] == "小明"

    index = json.loads((tmp_path / "students" / "index.json").read_text(encoding="utf-8"))
    assert index["counter"] == 1
    assert index["entries"]["p_0001"]["attributes.disabilities"] == ["visual"]
    assert created["framework"]["weights"]


def test_restart_reads_back(tmp_path):
    service = _service(tmp_path)
    created = service.create_student(CreateStudentRequest(name="小明", attributes=_attributes()))

    reopened = _service(tmp_path)
    loaded = reopened.get_student(created["profile_id"])
    assert loaded["name"] == "小明"
    assert loaded["attributes"]["disabilities"] == ["visual"]


def test_idempotency_conflict(tmp_path):
    service = _service(tmp_path)
    request = CreateStudentRequest(
        client_request_id="req-1", name="小明", attributes=_attributes()
    )
    service.create_student(request)
    with pytest.raises(ConflictError):
        service.create_student(request)
    # 只落一个分片
    assert len(list((tmp_path / "students").glob("p_*.json"))) == 1


def test_update_and_delete(tmp_path):
    service = _service(tmp_path)
    created = service.create_student(CreateStudentRequest(name="小明", attributes=_attributes()))

    updated = service.update_student(
        created["profile_id"],
        UpdateStudentRequest(attributes=_attributes(disabilities=["autism"], severity="severe", rehab_goals=[])),
    )
    assert updated["updated_at"] >= created["updated_at"]
    assert updated["attributes"]["disabilities"] == ["autism"]

    service.delete_student(created["profile_id"])
    assert not (tmp_path / "students" / "p_0001.json").exists()
    index = json.loads((tmp_path / "students" / "index.json").read_text(encoding="utf-8"))
    assert "p_0001" not in index["entries"]


def test_list_filter_and_paging(tmp_path):
    service = _service(tmp_path)
    service.create_student(CreateStudentRequest(name="A", attributes=_attributes()))
    service.create_student(
        CreateStudentRequest(name="B", attributes=_attributes(disabilities=["autism"]))
    )
    listed = service.list_students(disability="autism")
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "B"


def test_index_consistent_with_shards(tmp_path):
    service = _service(tmp_path)
    for name in ("A", "B", "C"):
        service.create_student(CreateStudentRequest(name=name, attributes=_attributes()))

    collection = service.repository.collection
    collection.reindex()
    items, total = collection.list(size=100)
    assert total == 3
    for item in items:
        payload = collection.get(item["id"])
        assert payload["profile_id"] == item["id"]

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
