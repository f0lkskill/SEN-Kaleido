"""学生画像生成服务：汇总学生证据并调用视觉模型分析。

数据流：
``evidence``（文本 + 图像附件）→ 视觉模型（DeepSeek ``deepseek-flash``）
→ 结构化画像 → 写回学生档案 ``StudentEvaluationProfile.portrait``。

视频不直接送入视觉模型，使用证据中已结构化的文字描述；
图像附件会转为 data URL 随消息发送。
"""

import base64
import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from kaleido.common.config import load_yaml
from kaleido.common.errors import ValidationError
from kaleido.common.logging import get_logger
from kaleido.common.paths import EVIDENCE_MEDIA_DIR, WEB_DIR
from kaleido.evidence.repository import EvidenceRepository
from kaleido.forge.llm_client import LLMClient, create_client
from kaleido.forge.prompts import render
from kaleido.profile.config_loader import load_config
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault

logger = get_logger("forge.portrait")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_SUFFIXES = {".txt", ".md"}
MAX_TEXT_CHARS = 4000

SEVERITY_LABELS = {"mild": "轻度", "moderate": "中度", "severe": "重度"}
SENSORY_LABELS = {
    "visual_first": "视觉优先",
    "audio_first": "听觉优先",
    "tactile_aided": "触觉辅助",
    "mixed": "综合",
}
PACE_LABELS = {"fast": "较快", "medium": "适中", "slow": "较慢"}
GOAL_LABELS = {
    "language": "语言",
    "sensory_integration": "感知统合",
    "social": "社交",
    "cognitive": "认知",
}


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


def _is_relative_to(path: Path, root: Path) -> bool:
    """判断路径是否位于指定根目录内，防止路径穿越。"""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class PortraitService:
    """基于证据生成学生画像。"""

    def __init__(
        self,
        profile_service: ProfileService | None = None,
        evidence_repository: EvidenceRepository | None = None,
        client: LLMClient | None = None,
        vault: Vault | None = None,
        config: dict | None = None,
    ):
        self.config = config or load_yaml("forge", "forge")
        self.client = client or create_client(self.config.get("llm", {}))
        self.profile_service = profile_service or ProfileService()
        self.evidence = evidence_repository or EvidenceRepository(vault=vault)
        settings = self.config.get("portrait", {})
        self.max_images = int(settings.get("max_images", 6))
        self.max_image_bytes = int(settings.get("max_image_bytes", 8 * 1024 * 1024))
        self.max_evidence = int(settings.get("max_evidence", 200))

    def generate(self, profile_id: str) -> dict:
        """汇总学生证据、调用视觉模型并写回画像。"""
        profile = self.profile_service.get_student(profile_id)
        items = self._load_evidence(profile_id)
        if not items:
            raise ValidationError("该学生暂无可用证据，无法生成画像")

        observation_names = self._observation_names(profile)
        evidence_text, image_parts, stats = self._build_evidence(items, observation_names)
        messages = self._build_messages(profile, evidence_text, image_parts)
        logger.info(
            "开始生成学生画像: student=%s evidence=%d images=%d videos=%d",
            profile_id,
            len(items),
            stats["images"],
            stats["videos"],
        )

        overrides: dict[str, Any] = {
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        vision_model = str(
            self.config.get("llm", {}).get("vision_model")
            or self.config.get("llm", {}).get("model")
            or ""
        ).strip()
        if vision_model:
            overrides["model"] = vision_model
        result = self.client.complete(messages, **overrides)
        parsed = self._parse_result(result.content)
        portrait = {
            "summary": parsed["summary"],
            "strengths": parsed["strengths"],
            "needs": parsed["needs"],
            "suggestions": parsed["suggestions"],
            "evidence_count": len(items),
            "image_count": stats["images"],
            "video_count": stats["videos"],
            "model": result.model,
            "generated_at": _now(),
        }
        saved = self.profile_service.save_portrait(profile_id, portrait)
        logger.info(
            "学生画像生成完成: student=%s model=%s tokens=%s",
            profile_id,
            result.model,
            (result.usage or {}).get("total_tokens"),
        )
        return {"profile": saved, "portrait": saved.get("portrait"), "usage": result.usage}

    def _load_evidence(self, profile_id: str) -> list[dict]:
        """读取该学生非驳回证据，按采集时间倒序。"""
        items, _ = self.evidence.list(
            {"student_id": profile_id},
            page=1,
            size=self.max_evidence,
        )
        usable = [
            item
            for item in items
            if item.get("scope") != "public" and item.get("status") != "rejected"
        ]
        usable.sort(key=lambda item: str(item.get("collected_at") or ""), reverse=True)
        return usable[: self.max_evidence]

    @staticmethod
    def _observation_names(profile: dict) -> dict[str, str]:
        """从学生评价框架提取观测点中文名。"""
        names: dict[str, str] = {}
        framework = profile.get("framework") or {}
        for indicator in framework.get("indicators") or []:
            for observation in indicator.get("observations") or []:
                key = str(observation.get("key") or "")
                if key:
                    names[key] = str(observation.get("name") or key)
        return names

    def _build_evidence(
        self, items: list[dict], observation_names: dict[str, str]
    ) -> tuple[str, list[dict], dict[str, int]]:
        """把证据整理为文本清单，并提取可送入视觉模型的图像。"""
        source_defs = load_config("evidence_sources").get("evidence_sources", {})
        lines: list[str] = []
        image_parts: list[dict] = []
        stats = {"images": 0, "videos": 0}

        for index, item in enumerate(items, start=1):
            source_type = str(item.get("source_type") or "")
            source = source_defs.get(source_type) or {}
            source_name = str(source.get("name") or source_type or "未知来源")
            media_type = str(item.get("media_type") or "text")
            status = str(item.get("status") or "draft")
            observation_key = str(item.get("observation_key") or "")
            observation_name = observation_names.get(observation_key, observation_key or "未指定")
            title = str(item.get("title") or observation_name)

            lines.append(f"【证据 {index}】{title}")
            lines.append(f"- ID：{item.get('evidence_id') or '-'}")
            lines.append(f"- 观测点：{observation_name}")
            lines.append(f"- 来源：{source_name}")
            lines.append(f"- 媒体：{media_type}")
            lines.append(f"- 状态：{status}")
            lines.append(f"- 采集时间：{item.get('collected_at') or '-'}")
            if item.get("collector"):
                lines.append(f"- 采集人：{item['collector']}")
            if item.get("value") is not None:
                lines.append(f"- 量化值：{item['value']}")
            if item.get("level") is not None:
                lines.append(f"- 等级：{item['level']} 级")
            if media_type == "video":
                stats["videos"] += 1
                lines.append("- 说明：视频未直接输入画面，使用下方结构化描述。")

            content = str(item.get("content") or "").strip()
            for attachment in item.get("attachments") or []:
                parsed = self._read_attachment(str(attachment))
                if parsed is None:
                    continue
                kind, value = parsed
                if kind == "image":
                    if stats["images"] >= self.max_images:
                        continue
                    image_parts.append(value)
                    stats["images"] += 1
                    lines.append(f"- 图像附件：已作为视觉输入（第 {stats['images']} 张）")
                elif kind == "text" and value and value not in content:
                    content = f"{content}\n[附件文本]\n{value}".strip()

            if content:
                lines.append(f"- 内容：{content}")
            if item.get("note"):
                lines.append(f"- 备注：{item['note']}")
            lines.append("")

        return "\n".join(lines).strip(), image_parts, stats

    def _read_attachment(self, url: str) -> tuple[str, Any] | None:
        """读取附件：图像转为视觉内容块，文本读取为有限长度字符串。"""
        if url.startswith("data:image/"):
            if ";base64," not in url:
                return None
            header, encoded = url.split(",", 1)
            mime = header[5:].split(";")[0] or "image/png"
            if len(encoded) > self.max_image_bytes * 2:
                return None
            return ("image", {"type": "image_url", "image_url": {"url": url}})

        path = self._resolve_local_path(url)
        if path is None or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            if path.stat().st_size > self.max_image_bytes:
                logger.warning("图像超过大小限制，已跳过: %s", path.name)
                return None
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return (
                "image",
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            )
        if suffix in TEXT_SUFFIXES:
            return ("text", path.read_text(encoding="utf-8", errors="ignore")[:MAX_TEXT_CHARS])
        return None

    @staticmethod
    def _resolve_local_path(url: str) -> Path | None:
        """把证据附件 URL 解析为受控的本地文件路径。"""
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        if path.startswith("/api/v1/evidence/files/"):
            name = path.rsplit("/", 1)[-1]
            if not name or Path(name).name != name:
                return None
            candidate = (EVIDENCE_MEDIA_DIR / name).resolve()
            root = EVIDENCE_MEDIA_DIR.resolve()
            return candidate if _is_relative_to(candidate, root) else None
        if path.startswith("/assets/"):
            relative = path[len("/assets/") :]
            if not relative or ".." in Path(relative).parts:
                return None
            root = (WEB_DIR / "assets").resolve()
            candidate = (root / relative).resolve()
            return candidate if _is_relative_to(candidate, root) else None
        return None

    def _build_messages(
        self, profile: dict, evidence_text: str, image_parts: list[dict]
    ) -> list[dict]:
        """拼装视觉分析消息。"""
        attributes = profile.get("attributes") or {}
        framework = profile.get("framework") or {}
        types = load_yaml("profile", "student_types").get("student_types", {})
        disabilities = [
            str((types.get(key) or {}).get("name") or key)
            for key in attributes.get("disabilities") or []
        ]
        mapping = {
            "name": profile.get("name", ""),
            "disabilities": "、".join(disabilities) or "未填写",
            "severity": SEVERITY_LABELS.get(
                str(attributes.get("severity") or ""), str(attributes.get("severity") or "")
            ),
            "cognitive_level": str(attributes.get("cognitive_level") or ""),
            "sensory_preference": SENSORY_LABELS.get(
                str(attributes.get("sensory_preference") or ""),
                str(attributes.get("sensory_preference") or ""),
            ),
            "learning_pace": PACE_LABELS.get(
                str(attributes.get("learning_pace") or ""),
                str(attributes.get("learning_pace") or ""),
            ),
            "rehab_goals": "、".join(
                GOAL_LABELS.get(str(goal), str(goal))
                for goal in attributes.get("rehab_goals") or []
            )
            or "未填写",
            "weights": json.dumps(framework.get("weights") or {}, ensure_ascii=False),
            "dimension_indexes": json.dumps(
                framework.get("dimension_indexes") or {}, ensure_ascii=False
            ),
            "evidence_text": evidence_text,
        }
        system_prompt = render("portrait_layer", mapping)
        if image_parts:
            user_content: Any = [
                {
                    "type": "text",
                    "text": "请结合系统提示中的证据清单和随消息附上的图像，生成学生画像 JSON。",
                },
                *image_parts,
            ]
        else:
            user_content = "请根据系统提示中的证据清单生成学生画像 JSON。"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _parse_result(content: str) -> dict:
        """解析模型 JSON；失败时把原文作为画像描述，避免整次分析作废。"""
        text = (content or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", text)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            logger.warning("画像 JSON 解析失败，回退为纯文本描述")
            return {"summary": text, "strengths": [], "needs": [], "suggestions": []}

        def as_list(*keys: str) -> list[str]:
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return [str(item).strip() for item in value if str(item).strip()][:4]
                if isinstance(value, str) and value.strip():
                    return [value.strip()]
            return []

        summary = str(
            data.get("summary")
            or data.get("description")
            or data.get("画像描述")
            or ""
        ).strip()
        return {
            "summary": summary or text,
            "strengths": as_list("strengths", "优势"),
            "needs": as_list("needs", "需求"),
            "suggestions": as_list("suggestions", "建议", "教学建议"),
        }
