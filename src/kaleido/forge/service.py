"""forge 业务服务：把学生画像 + 生成要求组合为 Prompt 并调用模型。"""

import json
from collections.abc import Callable, Iterator

from kaleido.common.config import load_yaml
from kaleido.common.errors import (
    ConfigError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from kaleido.common.logging import get_logger
from kaleido.forge.llm_client import LLMClient, create_client
from kaleido.forge.models import GenerateRequest
from kaleido.forge.prompts import load_template, render
from kaleido.forge.quality import analyze
from kaleido.profile.service import ProfileService
from kaleido.rules.service import PromptRuleService
from kaleido.vault import Vault

_logger = get_logger("forge.service")


class ForgeService:
    """资源生成服务。"""

    def __init__(
        self,
        client: LLMClient | None = None,
        profile_service: ProfileService | None = None,
        vault: Vault | None = None,
        config: dict | None = None,
        rule_service: PromptRuleService | None = None,
    ):
        self.config = config or load_yaml("forge", "forge")
        self.client: LLMClient = client or create_client(self.config.get("llm", {}))
        self.profile_service = profile_service or ProfileService()
        self.vault = vault or Vault()
        # 资源落库到 vault 的 resources 集合（envelope=true，带创建/更新时间）
        self.resources = self.vault.collection("resources")
        self.rule_service = rule_service or PromptRuleService(vault=self.vault)

    def _resolve_context(
        self, request: GenerateRequest
    ) -> tuple[dict, dict | None, list[dict]]:
        """解析学生属性、画像与该学生病症下已通过的通用规则。"""
        if request.profile_id:
            profile = self.profile_service.get_student(request.profile_id)
            attributes = profile["attributes"]
            return (
                attributes,
                profile.get("portrait"),
                self._approved_rules(attributes),
            )
        if request.attributes is not None:
            preview = self.profile_service.preview_framework(request.attributes)
            attributes = preview["attributes"]
            return attributes, None, self._approved_rules(attributes)
        if request.source_resource_id:
            source = self.get_resource(request.source_resource_id)
            source_profile_id = source.get("profile_id")
            if source_profile_id:
                profile = self.profile_service.get_student(str(source_profile_id))
                attributes = profile["attributes"]
                return (
                    attributes,
                    profile.get("portrait"),
                    self._approved_rules(attributes),
                )
            if source.get("attributes"):
                attributes = source["attributes"]
                return attributes, None, self._approved_rules(attributes)
        raise ValidationError("必须提供 profile_id、attributes 或 source_resource_id")

    def _approved_rules(self, attributes: dict) -> list[dict]:
        """取该学生全部病症下已通过审核的通用规则。"""
        return self.rule_service.approved_for(self._disabilities(attributes))

    @staticmethod
    def _portrait_text(portrait: dict | None) -> str:
        """把学生画像整理为可拼入 Prompt 的文本。"""
        if not portrait or not portrait.get("summary"):
            return ""
        lines = [str(portrait["summary"]).strip()]
        for label, key in (
            ("优势表现", "strengths"),
            ("需要支持", "needs"),
            ("教学建议", "suggestions"),
            ("个性强化提示（仅适用于该学生）", "personal_prompts"),
        ):
            values = portrait.get(key) or []
            if values:
                lines.append(f"{label}：" + "；".join(str(item) for item in values))
        return "\n".join(lines)

    @staticmethod
    def _disabilities(attributes: dict) -> list[str]:
        """取全部障碍类型（有序、去空）。"""
        values = attributes.get("disabilities") or []
        return [str(item) for item in values if item]

    def _primary_disability(self, attributes: dict) -> str:
        """取主障碍类型；多障碍时取首项，缺失时返回空串。"""
        values = self._disabilities(attributes)
        return values[0] if values else ""

    def _disability_name(self, key: str) -> str:
        """障碍类型的中文名（取自 student_types 配置）。"""
        types = load_yaml("profile", "student_types").get("student_types", {})
        entry = types.get(key) or {}
        return str(entry.get("name") or key)

    @staticmethod
    def _requirement_of(template_key: str) -> str:
        """从模板中抽取「要求：」这一行的具体内容。"""
        try:
            text = load_template(template_key)
        except ConfigError:
            return ""
        prefix = "要求："
        for line in text.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

    def _extra_layer_requirements(self, attributes: dict, primary: str) -> str:
        """多障碍时的叠加说明：把主障碍之外每种障碍的适配要点合并。"""
        lines: list[str] = []
        for key in self._disabilities(attributes):
            if key == primary:
                continue
            requirement = self._requirement_of(f"{key}_layer")
            if not requirement:
                continue
            lines.append(f"- 本学生同时具备「{self._disability_name(key)}」：{requirement}")
        return "\n".join(lines)

    def _rules_block(self, rules: list[dict]) -> str:
        """把已审核的病症通用规则与使用边界拼入系统提示词。"""
        if not rules:
            return ""
        lines = [
            f"- 【{self._disability_name(str(item.get('disability') or ''))}】"
            f"{item.get('text')}"
            for item in rules
        ]
        return (
            "【病症通用生成规则】\n"
            "以下规则来自同类病症资源的质检沉淀，已由教师审核通过；"
            "它们描述的是共性问题，必须逐条落实：\n"
            + "\n".join(lines)
            + "\n\n【规则使用边界】\n"
            "- 病症通用规则适用于同类学生，不得写成该学生的个人经历或隐私。\n"
            "- 学生画像中的个性强化提示只适用于当前学生，不得泛化为通用规则。\n"
            "- 若通用规则与个性提示冲突，以个性提示为准，并采用更保守的支持策略。"
        )

    def _source_block(self, source_resource_id: str | None) -> str:
        """把原资源正文整理为修订上下文。"""
        if not source_resource_id:
            return ""
        source = self.get_resource(source_resource_id)
        content = str(source.get("content") or "").strip()
        max_chars = int((self.config.get("revision") or {}).get("max_source_chars", 6000))
        topic = str(source.get("topic") or "")
        return (
            f"【基于原资源修订】\n"
            f"- 原资源 ID：{source_resource_id}\n"
            f"- 原资源主题：{topic or '未填写'}\n"
            f"- 原资源正文（节选）：\n{content[:max_chars] or '（空）'}\n\n"
            "请基于原资源重新生成一份完整的新资源：保留有效的分层结构与短句风格，"
            "逐条落实病症通用规则与学生个性强化提示；不要只输出修改说明，也不要简单复制原文。"
        )

    def _build_messages(
        self,
        request: GenerateRequest,
        attributes: dict,
        portrait: dict | None = None,
        rules: list[dict] | None = None,
    ) -> tuple[list, str]:
        """拼装分层 Prompt，返回 (messages, 系统提示词)。"""
        labels = self.config.get("resource_types", {})
        if request.resource_type not in labels:
            raise ValidationError(f"未知资源类型: {request.resource_type}")

        template_key = attributes.get("prompt_template_key") or (
            f"{self._primary_disability(attributes)}_layer"
        )
        cognitive_labels = load_yaml("profile", "attributes").get("cognitive_level_labels", {})
        cognitive_key = attributes.get("cognitive_level", "")
        constraints = dict(attributes.get("adaptation_constraints") or {})
        if constraints.get("avoid_visual_ref"):
            # 视觉参照限制优先于“添加表情”类趣味性约束
            constraints["add_emoji"] = False
            constraints["visual_aid"] = False
        mapping = {
            "severity": attributes.get("severity", ""),
            "cognitive_level": cognitive_labels.get(cognitive_key, cognitive_key),
            "sensory_preference": attributes.get("sensory_preference", ""),
            "learning_pace": attributes.get("learning_pace", ""),
            "constraints": json.dumps(constraints, ensure_ascii=False),
            "avoid_visual_ref": "是" if constraints.get("avoid_visual_ref") else "否",
            "resource_type": labels[request.resource_type],
            "topic": request.topic,
            "extra": json.dumps(request.extra, ensure_ascii=False) if request.extra else "无",
        }
        system_prompt = render(template_key, mapping)
        # 多障碍：以主障碍模板为主体，叠加其余障碍的适配要点
        extras = self._extra_layer_requirements(attributes, self._primary_disability(attributes))
        if extras:
            system_prompt = f"{system_prompt}\n\n【多障碍叠加要求】\n{extras}"
        portrait_text = self._portrait_text(portrait)
        if portrait_text:
            system_prompt = (
                f"{system_prompt}\n\n【学生画像（基于证据生成）】\n{portrait_text}\n\n"
                "请将上述学生画像作为本次资源设计的重要依据，在内容难度、活动形式与"
                "支持策略上体现画像中的优势、需求与教学建议。"
            )
        rules_block = self._rules_block(rules or [])
        if rules_block:
            system_prompt = f"{system_prompt}\n\n{rules_block}"
        source_block = self._source_block(request.source_resource_id)
        if source_block:
            system_prompt = f"{system_prompt}\n\n{source_block}"
        if constraints.get("avoid_visual_ref"):
            system_prompt = (
                f"{system_prompt}\n\n【视觉参照硬性限制】\n"
                "- 禁止使用 emoji、图片、Markdown 表格、颜色块等视觉提示。\n"
                "- 改用编号清单、逐条朗读稿和教师口述指令。\n"
                "- 涉及颜色等视觉经验概念时，必须配可触摸实物、纹理、温度、形状或声音等替代线索。\n"
                "- 不要写“播放音频”等无法执行的指令；若需音频，写成“教师朗读”或“播放教师录音”。\n"
                "- 必须输出完整结尾，不得以半截标题或半句话结束。"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"请生成与「{request.topic}」相关的{labels[request.resource_type]}。",
            },
        ]
        return messages, system_prompt

    def generate(
        self,
        request: GenerateRequest,
        on_event: Callable[[dict], None] | None = None,
    ) -> dict:
        """生成资源并落库（流式累积，初始状态 draft，等待教师确认）。"""
        attributes, portrait, rules = self._resolve_context(request)
        self._build_messages(request, attributes, portrait, rules)

        resource_id = ""
        system_prompt = ""
        for event in self.generate_stream(request):
            if on_event is not None:
                on_event(event)
            event_type = event.get("type")
            if event_type == "error":
                raise UpstreamError(str(event.get("message") or "生成失败"))
            if event_type == "done":
                resource_id = str(event.get("resource_id") or "")
                system_prompt = str(event.get("prompt") or "")
        if not resource_id:
            raise UpstreamError("生成未返回资源 ID")
        document = self.resources.get(resource_id)
        return {"resource_id": resource_id, "prompt": system_prompt, **document}

    def generate_stream(self, request: GenerateRequest) -> Iterator[dict]:
        """流式生成资源。

        以事件流形式产出：``reasoning``（模型思考）→ ``content``（正文增量）
        → ``done``（落库完成，含 resource_id 与系统提示词）；失败产出 ``error``。
        正文为空时不入库，避免产生"空资源"。
        """
        try:
            attributes, portrait, rules = self._resolve_context(request)
            messages, system_prompt = self._build_messages(
                request, attributes, portrait, rules
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("流式生成前置校验失败: %s", exc)
            yield {"type": "error", "message": str(exc)}
            return

        _logger.info(
            "开始流式生成: type=%s topic=%s profile=%s",
            request.resource_type,
            request.topic,
            request.profile_id,
        )
        parts: list[str] = []
        stream_method = getattr(self.client, "stream", None)
        try:
            if stream_method is None:
                # 客户端不支持流式（如离线桩）：一次性产出正文
                result = self.client.complete(messages)
                parts.append(result.content)
                yield {"type": "content", "text": result.content}
            else:
                for event in stream_method(messages):
                    if event.get("type") == "content":
                        parts.append(event.get("text", ""))
                    yield event
        except Exception as exc:
            _logger.exception("流式生成失败")
            yield {"type": "error", "message": str(exc)}
            return

        content = "".join(parts).strip()
        if not content:
            yield {
                "type": "error",
                "message": "模型未返回正文内容（思考可能占满输出额度或达到上下文上限），"
                "请重试或精简输入",
            }
            return

        quality = analyze(content, request.resource_type)
        resource_id = self.resources.next_id()
        document = {
            "resource_type": request.resource_type,
            "topic": request.topic,
            "profile_id": request.profile_id,
            "disability": self._primary_disability(attributes),
            "content": content,
            "prompt_template_key": attributes.get("prompt_template_key", ""),
            "model": getattr(self.client, "model", ""),
            "usage": {},
            "status": "draft",
            "attributes": attributes,
            "source_resource_id": request.source_resource_id,
            "quality": quality,
        }
        self.resources.put(resource_id, document)
        _logger.info(
            "流式生成完成: resource_id=%s content_len=%d quality_issues=%d",
            resource_id,
            len(content),
            len(quality["issues"]),
        )
        yield {
            "type": "done",
            "resource_id": resource_id,
            "model": document["model"],
            "status": "draft",
            "prompt": system_prompt,
            "quality": quality,
        }

    def list_resources(
        self,
        resource_type: str | None = None,
        disability: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按条件分页列出资源。"""
        filters: dict[str, str] = {}
        if resource_type:
            filters["resource_type"] = resource_type
        if disability:
            filters["disability"] = disability
        if status:
            filters["status"] = status
        # 资源库列表需展示正文，使用 list_full 回读完整文档
        items, total = self.resources.list_full(filters, page=page, size=size)
        results = [
            {"resource_id": item["id"], **{k: v for k, v in item.items() if k != "id"}}
            for item in items
        ]
        return {"total": total, "page": page, "size": size, "items": results}

    def get_resource(self, resource_id: str) -> dict:
        """读取单个资源。"""
        try:
            document = self.resources.get(resource_id)
        except (FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"资源不存在: {resource_id}") from exc
        return {"resource_id": resource_id, **document}

    def update_resource_status(self, resource_id: str, status: str) -> dict:
        """更新资源审核状态（draft / approved / rejected）。"""
        if status not in {"draft", "approved", "rejected"}:
            raise ValidationError(f"未知资源状态: {status}")
        try:
            document = self.resources.get(resource_id)
        except (FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"资源不存在: {resource_id}") from exc
        facet = document.get("facet") or {}
        if status == "approved" and facet.get("blocking"):
            raise ValidationError("质量校验存在硬性错误，请修改资源并重新校验后再通过")
        document["status"] = status
        self.resources.put(resource_id, document)
        _logger.info("资源状态更新: id=%s status=%s", resource_id, status)
        return self.get_resource(resource_id)

    def delete_resource(self, resource_id: str) -> dict:
        """删除资源。"""
        try:
            self.resources.delete(resource_id)
        except (FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"资源不存在: {resource_id}") from exc
        _logger.info("资源已删除: id=%s", resource_id)
        return {"resource_id": resource_id, "deleted": True}

    def resource_types(self) -> dict:
        """返回可用资源类型。"""
        return self.config.get("resource_types", {})
