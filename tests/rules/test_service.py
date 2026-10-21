"""规则集服务测试：沉淀、去重、审核、删除与生成取用。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.rules.service import PromptRuleService
from kaleido.vault import Vault


def _service(tmp_path) -> PromptRuleService:
    return PromptRuleService(vault=Vault(data_dir=tmp_path))


def test_add_rules_dedup_and_pending(tmp_path):
    service = _service(tmp_path)
    added = service.add_rules(
        "visual",
        ["规则 A", "规则 A", "规则 B"],
        source_resource_id="r_1",
        source_topic="主题",
        source_score=80,
        model="m",
    )
    assert [item["text"] for item in added] == ["规则 A", "规则 B"]
    assert all(item["status"] == "pending" for item in added)
    assert added[0]["source_resource_id"] == "r_1"
    assert added[0]["source_topic"] == "主题"

    # 同一病症下相同文本不重复沉淀
    assert service.add_rules("visual", ["规则 A"]) == []
    # 不同病症允许存在相同文本
    hearing = service.add_rules("hearing", ["规则 A"])
    assert hearing[0]["disability"] == "hearing"


def test_approve_reject_delete_and_generation_selection(tmp_path):
    service = _service(tmp_path)
    added = service.add_rules("visual", ["视觉规则一", "视觉规则二"])
    first, second = added
    service.set_status(first["rule_id"], "approved")
    service.set_status(second["rule_id"], "rejected")

    approved = service.approved_for(["visual", "hearing"])
    assert [item["rule_id"] for item in approved] == [first["rule_id"]]
    assert service.approved_for(["hearing"]) == []

    service.set_status(second["rule_id"], "approved")
    assert len(service.approved_for(["visual"])) == 2

    service.delete_rule(first["rule_id"])
    remaining = service.list_rules()["items"]
    assert [item["rule_id"] for item in remaining] == [second["rule_id"]]


def test_list_filters(tmp_path):
    service = _service(tmp_path)
    service.add_rules("visual", ["A"])
    service.add_rules("hearing", ["B"])

    assert service.list_rules(disability="visual")["total"] == 1
    assert service.list_rules(status="pending")["total"] == 2
    assert service.list_rules(disability="visual", status="approved")["total"] == 0
