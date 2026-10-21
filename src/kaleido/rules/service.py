"""病症通用提示词规则集服务。

规则来源：资源质量校验模型提炼的「共性问题」。规则按病症归档，教师审核
通过后参与同类病症的资源生成；学生个体差异由画像中的个性提示承载。
"""

import hashlib
import re
from datetime import datetime

from kaleido.common.config import load_yaml
from kaleido.common.errors import NotFoundError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.rules.models import PromptRule
from kaleido.vault import Vault

logger = get_logger("rules.service")

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_STATUSES = {"pending", "approved", "rejected"}


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


def _normalize(text: str) -> str:
    """规则文本归一化：折叠空白，用于去重。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


class PromptRuleService:
    """按病症维护模型沉淀的通用生成规则。"""

    def __init__(self, vault: Vault | None = None, config: dict | None = None):
        self.vault = vault or Vault()
        self.rules = self.vault.collection("prompt_rules")
        self.config = config or load_yaml("rules", "rules")
        self._max_per_disability = int(
            self.config.get("max_rules_per_disability", 12)
        )
        self._max_chars = int(self.config.get("max_chars_per_rule", 240))

    def add_rules(
        self,
        disability: str,
        prompts: list[str],
        *,
        source_resource_id: str | None = None,
        source_topic: str = "",
        source_score: int | None = None,
        source_profile_id: str | None = None,
        model: str = "",
    ) -> list[dict]:
        """把模型提炼的共性问题写入指定病症的规则集（按文本去重）。"""
        key = str(disability or "").strip()
        if not key:
            raise ValidationError("规则必须归属一个病症")
        existing = {
            _normalize(str(item.get("text") or ""))
            for item in self.rules.iter_all()
            if item.get("disability") == key
        }
        now = _now()
        added: list[dict] = []
        for raw in prompts:
            text = _normalize(str(raw or ""))
            if not text or text in existing:
                continue
            text = text[: self._max_chars]
            normalized = _normalize(text)
            if normalized in existing:
                continue
            digest = hashlib.sha1(f"{key}:{normalized}".encode()).hexdigest()[:10]
            document = PromptRule(
                rule_id=f"pr_{digest}",
                disability=key,
                text=text,
                status="pending",
                source_resource_id=source_resource_id,
                source_topic=str(source_topic or ""),
                source_score=source_score,
                source_profile_id=source_profile_id,
                model=str(model or ""),
                created_at=now,
                updated_at=now,
            ).model_dump()
            self.rules.put(document["rule_id"], document)
            existing.add(normalized)
            added.append(document)
        if added:
            logger.info(
                "规则集新增规则: disability=%s count=%d source=%s",
                key,
                len(added),
                source_resource_id,
            )
        return added

    def list_rules(
        self,
        *,
        disability: str | None = None,
        status: str | None = None,
    ) -> dict:
        """列出全部模型记录的规则，可按病症/状态筛选。"""
        items = list(self.rules.iter_all())
        if disability:
            items = [item for item in items if item.get("disability") == disability]
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"items": items, "total": len(items)}

    def set_status(self, rule_id: str, status: str) -> dict:
        """审核规则：通过（approved）或拒绝（rejected）。"""
        if status not in _STATUSES:
            raise ValidationError(f"未知规则状态: {status}")
        document = self._get(rule_id)
        document["status"] = status
        document["updated_at"] = _now()
        self.rules.put(rule_id, document)
        logger.info("规则集审核: id=%s status=%s", rule_id, status)
        return document

    def delete_rule(self, rule_id: str) -> dict:
        """删除规则。"""
        self._get(rule_id)
        self.rules.delete(rule_id)
        logger.info("规则集删除: id=%s", rule_id)
        return {"rule_id": rule_id}

    def approved_for(self, disabilities: list[str]) -> list[dict]:
        """取学生所属病症下已通过审核的规则，用于资源生成。"""
        ordered = list(dict.fromkeys(str(item) for item in disabilities if item))
        wanted = set(ordered)
        if not wanted:
            return []
        grouped: dict[str, list[dict]] = {}
        for item in self.rules.iter_all():
            if item.get("status") != "approved":
                continue
            disability = str(item.get("disability") or "")
            if disability not in wanted:
                continue
            grouped.setdefault(disability, []).append(item)
        result: list[dict] = []
        for disability in ordered:
            items = sorted(
                grouped.get(disability, []),
                key=lambda item: str(item.get("created_at") or ""),
                reverse=True,
            )
            result.extend(items[: self._max_per_disability])
        return result

    def _get(self, rule_id: str) -> dict:
        """读取规则；不存在时统一抛 NotFoundError。"""
        try:
            return self.rules.get(rule_id)
        except Exception as exc:
            raise NotFoundError(f"规则不存在: {rule_id}") from exc
