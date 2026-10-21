"""facet 服务测试：规则拦截、模型评分与报告落库。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import NotFoundError, ValidationError
from kaleido.facet.models import FacetEvaluationRequest
from kaleido.facet.service import FacetService
from kaleido.forge.llm_client import StubClient
from kaleido.forge.service import ForgeService
from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault

_LLM_CONTENT = json.dumps(
    {
        "summary": "资源整体适合该生，但视觉线索仍可加强。",
        "scores": {
            "disability_fit": 90,
            "cognitive_load": 80,
            "sensory_accessibility": 70,
            "teaching_usability": 90,
        },
        "strengths": ["步骤清晰"],
        "issues": ["图像说明较少"],
        "suggestions": ["补充关键步骤图"],
        "common_prompts": [
            {
                "disability": "visual",
                "text": "补充关键步骤图，并配教师口述指令。",
            }
        ],
        "personal_prompts": ["该生对强光敏感，资源中应避免高亮闪烁提示。"],
    },
    ensure_ascii=False,
)


def _setup(tmp_path, content="朗读：春天来了。\n\n![春天](spring.png)"):
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
            "content": content,
            "status": "draft",
        },
    )
    client = StubClient(content=_LLM_CONTENT)
    service = FacetService(
        profile_service=profile_service,
        client=client,
        vault=vault,
    )
    return service, client, resources, resource_id, profile, vault


def test_evaluate_persists_report(tmp_path):
    service, client, resources, resource_id, profile, _ = _setup(tmp_path)
    report = service.evaluate(resource_id)
    assert report["verdict"] == "review"
    assert report["score"] == 83
    assert report["blocking"] is False
    assert report["model"] == "stub"
    assert report["dimensions"][0]["name"] == "障碍适配"
    assert report["summary"].startswith("资源整体适合")
    assert "补充关键步骤图" in report["suggestions"]
    assert report["prompts"] == ["补充关键步骤图，并配教师口述指令。"]
    assert report["common_prompts"] == [
        {"disability": "visual", "text": "补充关键步骤图，并配教师口述指令。"}
    ]
    assert report["personal_prompts"] == [
        "该生对强光敏感，资源中应避免高亮闪烁提示。"
    ]
    assert len(client.calls) == 1
    assert "max_tokens" not in client.calls[0]

    rules = service.rule_service.list_rules()["items"]
    assert len(rules) == 1
    assert rules[0]["disability"] == "visual"
    assert rules[0]["text"] == "补充关键步骤图，并配教师口述指令。"
    assert rules[0]["status"] == "pending"
    assert rules[0]["source_resource_id"] == resource_id

    saved_profile = service.profile_service.get_student(profile["profile_id"])
    assert saved_profile["portrait"]["personal_prompts"] == [
        "该生对强光敏感，资源中应避免高亮闪烁提示。"
    ]

    stored = service.get_report(resource_id)
    assert stored["score"] == 83
    saved_resource = resources.get(resource_id)
    assert saved_resource["facet"]["verdict"] == "review"


def test_rule_errors_block_and_prevent_approval(tmp_path):
    service, _, _, resource_id, _, vault = _setup(tmp_path, content="```\n代码")
    report = service.evaluate(resource_id)
    assert report["verdict"] == "fail"
    assert report["blocking"] is True
    forge = ForgeService(client=StubClient(), vault=vault)
    with pytest.raises(ValidationError):
        forge.update_resource_status(resource_id, "approved")


def test_rule_only_evaluation_skips_llm(tmp_path):
    service, client, _, resource_id, _, _ = _setup(tmp_path, content="朗读：春天来了。")
    report = service.evaluate(resource_id, FacetEvaluationRequest(use_llm=False))
    assert report["use_llm"] is False
    assert report["llm"] is None
    assert report["score"] == report["rule_score"]
    assert client.calls == []


def test_get_missing_report(tmp_path):
    service, _, _, resource_id, _, _ = _setup(tmp_path)
    with pytest.raises(NotFoundError):
        service.get_report(resource_id)


def test_llm_parse_failure_falls_back(tmp_path):
    service, client, _, resource_id, _, _ = _setup(tmp_path)
    client.content = "模型只返回了一段说明"
    report = service.evaluate(resource_id)
    assert report["llm"]["parsed"] is False
    assert report["verdict"] == "review"
    assert report["score"] == report["rule_score"]
    assert "回退为规则分" in report["summary"]


class _StreamingStub:
    """带流式能力的评分桩：先思考，再输出 JSON。"""

    def __init__(self, content: str):
        self.content = content
        self.model = "stub-stream"

    def complete(self, messages, **overrides):  # pragma: no cover
        raise AssertionError("流式路径不应调用 complete")

    def stream(self, messages, **overrides):
        yield {"type": "reasoning", "text": "先看规则。"}
        yield {"type": "content", "text": self.content}


def test_evaluate_streams_reasoning(tmp_path):
    """模型评分过程通过 on_event 实时上报思考与正文。"""
    service, _, _, resource_id, _, _ = _setup(tmp_path)
    service.client = _StreamingStub(_LLM_CONTENT)
    events: list[dict] = []

    report = service.evaluate(resource_id, on_event=events.append)

    assert any(event["type"] == "reasoning" for event in events)
    assert any(event["type"] == "content" for event in events)
    assert report["model"] == "stub-stream"
    assert report["verdict"] == "review"


def test_config_summary(tmp_path):
    service, _, _, _, _, _ = _setup(tmp_path)
    summary = service.config_summary()
    assert "disability_fit" in summary["dimensions"]
    assert summary["thresholds"]["pass"] == 80
