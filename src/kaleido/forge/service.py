"""forge 业务服务：把学生画像 + 生成要求组合为 Prompt 并调用模型。"""

import json
from collections.abc import Iterator

from kaleido.common.config import load_yaml
from kaleido.common.errors import ValidationError
from kaleido.common.logging import get_logger
from kaleido.forge.llm_client import LLMClient, create_client
from kaleido.forge.models import GenerateRequest
from kaleido.forge.prompts import render
from kaleido.profile.service import ProfileService
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
    ):
        self.config = config or load_yaml("forge", "forge")
        self.client: LLMClient = client or create_client(self.config.get("llm", {}))
        self.profile_service = profile_service or ProfileService()
        self.vault = vault or Vault()
        # 资源落库到 vault 的 resources 集合（envelope=true，带创建/更新时间）
        self.resources = self.vault.collection("resources")

    def _resolve_attributes(self, request: GenerateRequest) -> dict:
        """从已建档画像或临时属性中解析出规范化的学生属性。"""
        if request.profile_id:
            return self.profile_service.get_student(request.profile_id)["attributes"]
        if request.attributes is not None:
            preview = self.profile_service.preview_framework(request.attributes)
            return preview["attributes"]
        raise ValidationError("必须提供 profile_id 或 attributes")

    @staticmethod
    def _primary_disability(attributes: dict) -> str:
        """取主障碍类型；多障碍时取首项，缺失时返回空串。"""
        values = attributes.get("disabilities") or []
        return str(values[0]) if values else ""

    def _build_messages(self, request: GenerateRequest, attributes: dict) -> tuple[list, str]:
        """拼装分层 Prompt，返回 (messages, 系统提示词)。"""
        labels = self.config.get("resource_types", {})
        if request.resource_type not in labels:
            raise ValidationError(f"未知资源类型: {request.resource_type}")

        template_key = attributes.get("prompt_template_key") or (
            f"{self._primary_disability(attributes)}_layer"
        )
        mapping = {
            "severity": attributes.get("severity", ""),
            "cognitive_level": attributes.get("cognitive_level", ""),
            "sensory_preference": attributes.get("sensory_preference", ""),
            "learning_pace": attributes.get("learning_pace", ""),
            "constraints": json.dumps(
                attributes.get("adaptation_constraints", {}), ensure_ascii=False
            ),
            "resource_type": labels[request.resource_type],
            "topic": request.topic,
            "extra": json.dumps(request.extra, ensure_ascii=False) if request.extra else "无",
        }
        system_prompt = render(template_key, mapping)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"请生成与「{request.topic}」相关的{labels[request.resource_type]}。",
            },
        ]
        return messages, system_prompt

    def generate(self, request: GenerateRequest) -> dict:
        """生成资源并落库（初始状态 draft，等待教师确认）。"""
        attributes = self._resolve_attributes(request)
        messages, system_prompt = self._build_messages(request, attributes)
        _logger.info(
            "开始生成资源: type=%s topic=%s profile=%s",
            request.resource_type,
            request.topic,
            request.profile_id,
        )
        result = self.client.complete(messages)

        resource_id = self.resources.next_id()
        document = {
            "resource_type": request.resource_type,
            "topic": request.topic,
            "profile_id": request.profile_id,
            "disability": self._primary_disability(attributes),
            "content": result.content,
            "prompt_template_key": attributes.get("prompt_template_key", ""),
            "model": result.model,
            "usage": result.usage,
            "status": "draft",
        }
        self.resources.put(resource_id, document)
        _logger.info(
            "生成完成: resource_id=%s model=%s tokens=%s content_len=%d",
            resource_id,
            result.model,
            (result.usage or {}).get("total_tokens"),
            len(result.content or ""),
        )
        return {"resource_id": resource_id, "prompt": system_prompt, **document}

    def generate_stream(self, request: GenerateRequest) -> Iterator[dict]:
        """流式生成资源。

        以事件流形式产出：``reasoning``（模型思考）→ ``content``（正文增量）
        → ``done``（落库完成，含 resource_id 与系统提示词）；失败产出 ``error``。
        正文为空时不入库，避免产生"空资源"。
        """
        try:
            attributes = self._resolve_attributes(request)
            messages, system_prompt = self._build_messages(request, attributes)
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
                "message": "模型未返回正文内容（推理可能占满 max_tokens），请重试或提高 max_tokens",
            }
            return

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
        }
        self.resources.put(resource_id, document)
        _logger.info("流式生成完成: resource_id=%s content_len=%d", resource_id, len(content))
        yield {
            "type": "done",
            "resource_id": resource_id,
            "model": document["model"],
            "status": "draft",
            "prompt": system_prompt,
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
        return {"resource_id": resource_id, **self.resources.get(resource_id)}

    def resource_types(self) -> dict:
        """返回可用资源类型。"""
        return self.config.get("resource_types", {})
