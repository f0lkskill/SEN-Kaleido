"""forge 服务测试：画像解析、Prompt 拼装、落库与筛选。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import NotFoundError, ValidationError
from kaleido.forge.llm_client import StubClient
from kaleido.forge.models import GenerateRequest
from kaleido.forge.service import ForgeService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _setup(tmp_path):
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    client = StubClient(content="生成的课件")
    service = ForgeService(
        client=client, profile_service=profile_service, vault=Vault(data_dir=tmp_path)
    )
    return service, profile_service, client


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


def test_generate_from_profile(tmp_path):
    service, profile_service, _ = _setup(tmp_path)
    profile = profile_service.create_student(
        CreateStudentRequest(name="小明", attributes=_attributes())
    )
    result = service.generate(
        GenerateRequest(
            profile_id=profile["profile_id"], resource_type="courseware", topic="认识四季"
        )
    )
    assert result["resource_id"] == "r_00001"
    assert result["content"] == "生成的课件"
    assert result["disability"] == "visual"
    assert "视力障碍" in result["prompt"]
    assert "voice_first" in result["prompt"]

    stored = service.get_resource("r_00001")
    assert stored["content"] == "生成的课件"
    assert stored["status"] == "draft"


def test_generate_from_attributes(tmp_path):
    service, _, client = _setup(tmp_path)
    result = service.generate(
        GenerateRequest(attributes=_attributes(), resource_type="exercise", topic="十以内加法")
    )
    assert result["prompt_template_key"] == "visual_layer"
    assert client.calls, "应调用一次模型"


def test_missing_source_raises(tmp_path):
    service, _, _ = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.generate(GenerateRequest(resource_type="courseware", topic="x"))


def test_unknown_resource_type_raises(tmp_path):
    service, _, _ = _setup(tmp_path)
    with pytest.raises(ValidationError):
        service.generate(
            GenerateRequest(attributes=_attributes(), resource_type="video", topic="x")
        )


def test_list_and_filter(tmp_path):
    service, _, _ = _setup(tmp_path)
    service.generate(
        GenerateRequest(attributes=_attributes(), resource_type="courseware", topic="A")
    )
    service.generate(
        GenerateRequest(
            attributes=_attributes(disabilities=["autism"]), resource_type="exercise", topic="B"
        )
    )
    listed = service.list_resources(resource_type="courseware")
    assert listed["total"] == 1
    assert listed["items"][0]["resource_id"] == "r_00001"

    assert service.resource_types()["courseware"] == "分层知识点课件"

class _StreamingStub:
    """带流式能力的桩：先产出推理，再产出正文。"""

    def __init__(self, content: str = "流式正文"):
        self.content = content
        self.model = "stub-stream"

    def complete(self, messages, **overrides):  # pragma: no cover - 不应被调用
        raise AssertionError("流式路径不应调用 complete")

    def stream(self, messages, **overrides):
        yield {"type": "reasoning", "text": "思考…"}
        yield {"type": "content", "text": self.content}


def test_update_status_and_delete(tmp_path):
    service, _, _ = _setup(tmp_path)
    service.generate(
        GenerateRequest(attributes=_attributes(), resource_type="courseware", topic="A")
    )
    updated = service.update_resource_status("r_00001", "approved")
    assert updated["status"] == "approved"
    assert service.get_resource("r_00001")["status"] == "approved"

    with pytest.raises(ValidationError):
        service.update_resource_status("r_00001", "unknown")
    with pytest.raises(NotFoundError):
        service.get_resource("r_99999")

    service.delete_resource("r_00001")
    assert service.list_resources()["total"] == 0


def test_generate_stream(tmp_path):
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    service = ForgeService(
        client=_StreamingStub(),
        profile_service=profile_service,
        vault=Vault(data_dir=tmp_path),
    )
    events = list(
        service.generate_stream(
            GenerateRequest(attributes=_attributes(), resource_type="courseware", topic="x")
        )
    )
    types = [event["type"] for event in events]
    assert "reasoning" in types
    assert events[-1]["type"] == "done"
    assert events[-1]["resource_id"] == "r_00001"
    assert service.get_resource("r_00001")["content"] == "流式正文"


def test_generate_stream_stub_fallback(tmp_path):
    # StubClient 不带 stream，应退化为一次性产出正文并入库存档
    service, _, _ = _setup(tmp_path)
    events = list(
        service.generate_stream(
            GenerateRequest(attributes=_attributes(), resource_type="courseware", topic="x")
        )
    )
    assert events[-1]["type"] == "done"
    assert events[-1]["resource_id"] == "r_00001"


def test_generate_stream_error_on_missing_source(tmp_path):
    service, _, _ = _setup(tmp_path)
    events = list(service.generate_stream(GenerateRequest(resource_type="courseware", topic="x")))
    assert events[0]["type"] == "error"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
