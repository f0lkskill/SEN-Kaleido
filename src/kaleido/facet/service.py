"""facet 业务服务：规则校验 + 模型适配度评分 + 质量报告落库。"""

import json
import re
from datetime import datetime

from kaleido.common.config import load_yaml
from kaleido.common.errors import NotFoundError
from kaleido.common.logging import get_logger
from kaleido.facet.models import FacetEvaluationRequest, FacetReport
from kaleido.facet.rules import evaluate as evaluate_rules
from kaleido.forge.llm_client import LLMClient, create_client
from kaleido.forge.prompts import render
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault

logger = get_logger("facet.service")

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

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


class FacetService:
    """资源质量校验服务。"""

    def __init__(
        self,
        profile_service: ProfileService | None = None,
        client: LLMClient | None = None,
        vault: Vault | None = None,
        config: dict | None = None,
    ):
        self.config = config or load_yaml("facet", "facet")
        self.profile_service = profile_service or ProfileService()
        self.client = client or create_client(
            load_yaml("forge", "forge").get("llm", {})
        )
        self.vault = vault or Vault()
        self.resources = self.vault.collection("resources")

    def evaluate(
        self, resource_id: str, request: FacetEvaluationRequest | None = None
    ) -> dict:
        """校验资源并保存质量报告。"""
        req = request or FacetEvaluationRequest()
        document = self._load_resource(resource_id)
        profile = self._load_profile(document.get("profile_id"))
        attributes = (profile or {}).get("attributes") or document.get("attributes") or {}
        content = str(document.get("content") or "")
        resource_type = str(document.get("resource_type") or "")

        rules = evaluate_rules(content, resource_type, attributes, self.config)
        llm = None
        if req.use_llm:
            llm = self._score_with_llm(
                document, profile, attributes, rules, content, resource_type
            )

        weights = self.config.get("weights") or {}
        scores = (llm or {}).get("scores") or {}
        score = self._weighted_score(scores, weights, int(rules["score"]))
        thresholds = self.config.get("thresholds") or {}
        verdict = self._verdict(
            score,
            rules,
            pass_score=int(thresholds.get("pass", 80)),
            review_score=int(thresholds.get("review", 60)),
            has_llm_issues=bool((llm or {}).get("issues")),
            llm_incomplete=bool(
                llm and (llm.get("parsed") is False or llm.get("truncated"))
            ),
        )
        report = FacetReport(
            resource_id=resource_id,
            profile_id=document.get("profile_id"),
            verdict=verdict,
            score=score,
            rule_score=int(rules["score"]),
            blocking=bool(rules["blocking"]),
            rules=rules,
            dimensions=self._dimensions(scores, weights),
            summary=self._summary(llm, rules),
            strengths=(llm or {}).get("strengths") or [],
            issues=(llm or {}).get("issues") or [],
            suggestions=self._suggestions(llm, rules),
            prompts=(llm or {}).get("prompts") or [],
            llm=llm,
            use_llm=req.use_llm,
            model=str((llm or {}).get("model") or ""),
            usage=(llm or {}).get("usage") or {},
            evaluated_at=_now(),
        ).model_dump()

        document["facet"] = report
        self.resources.put(resource_id, document)
        if report["prompts"] and report["profile_id"]:
            try:
                self.profile_service.add_prompt_board_items(
                    str(report["profile_id"]),
                    [
                        {
                            "text": prompt,
                            "source_resource_id": resource_id,
                            "source_topic": document.get("topic", ""),
                            "source_score": score,
                            "model": report["model"],
                        }
                        for prompt in report["prompts"]
                    ],
                )
            except NotFoundError:
                logger.warning(
                    "资源关联学生不存在，提示词未写入规则板: %s", report["profile_id"]
                )
        logger.info(
            "资源质量校验完成: id=%s verdict=%s score=%d blocking=%s use_llm=%s",
            resource_id,
            verdict,
            score,
            report["blocking"],
            req.use_llm,
        )
        return report

    def get_report(self, resource_id: str) -> dict:
        """读取资源最近一次质量报告。"""
        document = self._load_resource(resource_id)
        report = document.get("facet")
        if not isinstance(report, dict):
            raise NotFoundError(f"资源尚未进行质量校验: {resource_id}")
        return report

    def config_summary(self) -> dict:
        """返回前端展示所需的维度、权重与阈值。"""
        return {
            "dimensions": self.config.get("dimensions", {}),
            "weights": self.config.get("weights", {}),
            "thresholds": {
                key: (self.config.get("thresholds") or {}).get(key)
                for key in ("pass", "review")
            },
        }

    def _load_resource(self, resource_id: str) -> dict:
        """读取资源文档。"""
        try:
            return self.resources.get(resource_id)
        except (FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"资源不存在: {resource_id}") from exc

    def _load_profile(self, profile_id: str | None) -> dict | None:
        """读取资源关联的学生档案；档案已删除时回退资源内快照。"""
        if not profile_id:
            return None
        try:
            return self.profile_service.get_student(str(profile_id))
        except NotFoundError:
            logger.warning("资源关联的学生档案不存在，使用资源属性快照: %s", profile_id)
            return None

    def _score_with_llm(
        self,
        document: dict,
        profile: dict | None,
        attributes: dict,
        rules: dict,
        content: str,
        resource_type: str,
    ) -> dict:
        """调用模型输出适配度评分与质性问题。"""
        thresholds = self.config.get("thresholds") or {}
        max_chars = int(thresholds.get("max_content_chars", 6000))
        mapping = {
            "resource_type": resource_type,
            "topic": document.get("topic", ""),
            "attributes": self._attributes_text(attributes),
            "portrait": self._portrait_text((profile or {}).get("portrait")),
            "rules": self._rules_text(rules),
            "content": content[:max_chars] or "（空）",
        }
        system_prompt = render("facet_evaluation", mapping)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "请输出质量评分 JSON。"},
        ]
        logger.info(
            "开始模型质量评分: resource=%s type=%s content_len=%d",
            document.get("resource_id") or "",
            resource_type,
            len(content),
        )
        result = self.client.complete(
            messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = self._parse_result(result.content)
        parsed["model"] = result.model
        parsed["usage"] = result.usage
        parsed["finish_reason"] = getattr(result, "finish_reason", "")
        parsed["truncated"] = parsed["finish_reason"] == "length"
        return parsed

    def _attributes_text(self, attributes: dict) -> str:
        """把学生属性整理为可读文本。"""
        types = load_yaml("profile", "student_types").get("student_types", {})
        cognitive = load_yaml("profile", "attributes").get(
            "cognitive_level_labels", {}
        )
        disabilities = "、".join(
            str((types.get(key) or {}).get("name") or key)
            for key in attributes.get("disabilities") or []
        )
        severity = str(attributes.get("severity") or "")
        cognitive_key = str(attributes.get("cognitive_level") or "")
        sensory = str(attributes.get("sensory_preference") or "")
        pace = str(attributes.get("learning_pace") or "")
        goals = "、".join(
            GOAL_LABELS.get(str(goal), str(goal))
            for goal in attributes.get("rehab_goals") or []
        )
        lines = [
            f"- 障碍类型：{disabilities or '未填写'}",
            f"- 障碍程度：{SEVERITY_LABELS.get(severity, severity or '未填写')}",
            f"- 认知等级：{cognitive.get(cognitive_key, cognitive_key or '未填写')}",
            f"- 感官偏好：{SENSORY_LABELS.get(sensory, sensory or '未填写')}",
            f"- 学习节奏：{PACE_LABELS.get(pace, pace or '未填写')}",
            f"- 康复目标：{goals or '未填写'}",
        ]
        constraints = attributes.get("adaptation_constraints") or {}
        if constraints:
            lines.append(
                f"- 适配约束：{json.dumps(constraints, ensure_ascii=False)}"
            )
        return "\n".join(lines)

    @staticmethod
    def _portrait_text(portrait: dict | None) -> str:
        """把学生画像整理为 Prompt 文本。"""
        if not portrait or not portrait.get("summary"):
            return "该学生尚未生成画像，请主要依据学生属性评估。"
        lines = [str(portrait["summary"]).strip()]
        for label, key in (
            ("优势表现", "strengths"),
            ("需要支持", "needs"),
            ("教学建议", "suggestions"),
        ):
            values = portrait.get(key) or []
            if values:
                lines.append(f"{label}：" + "；".join(str(item) for item in values))
        return "\n".join(lines)

    @staticmethod
    def _rules_text(rules: dict) -> str:
        """把规则命中项整理为 Prompt 文本。"""
        issues = rules.get("issues") or []
        if not issues:
            return "未发现规则问题。"
        lines = []
        for issue in issues:
            label = "硬性错误" if issue.get("level") == "error" else "警告"
            line = f"- [{label}] {issue.get('message')}"
            if issue.get("suggestion"):
                line += f"（建议：{issue['suggestion']}）"
            lines.append(line)
        stats = rules.get("stats") or {}
        lines.append(
            f"- 统计：{stats.get('characters', 0)} 字，"
            f"{stats.get('sentences', 0)} 句，"
            f"最长句 {stats.get('max_length', 0)} 字"
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_result(content: str) -> dict:
        """解析模型 JSON；解析失败时保留原文摘要，避免整次校验作废。"""
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
            logger.warning("质量评分 JSON 解析失败，回退为规则分")
            return {
                "summary": "模型评分返回格式不完整，本次综合分回退为规则分。",
                "scores": {},
                "strengths": [],
                "issues": [],
                "suggestions": [],
                "prompts": [],
                "parsed": False,
            }

        raw_scores = data.get("scores")
        scores: dict[str, int] = {}
        if isinstance(raw_scores, dict):
            for key, value in raw_scores.items():
                try:
                    scores[str(key)] = max(0, min(100, int(float(value))))
                except (TypeError, ValueError):
                    continue

        def as_list(*keys: str) -> list[str]:
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return [
                        str(item).strip() for item in value if str(item).strip()
                    ][:4]
                if isinstance(value, str) and value.strip():
                    return [value.strip()]
            return []

        summary = str(
            data.get("summary") or data.get("description") or data.get("总结") or ""
        ).strip()
        return {
            "summary": summary or text,
            "scores": scores,
            "strengths": as_list("strengths", "优势"),
            "issues": as_list("issues", "问题"),
            "suggestions": as_list("suggestions", "建议", "教学建议"),
            "prompts": as_list("prompts", "提示词", "生成提示词"),
            "parsed": True,
        }

    def _dimensions(self, scores: dict, weights: dict) -> list[dict]:
        """按配置顺序组装维度评分。"""
        names = self.config.get("dimensions") or {}
        return [
            {
                "key": key,
                "name": str(name),
                "weight": float(weights.get(key, 0)),
                "score": scores.get(key),
            }
            for key, name in names.items()
        ]

    @staticmethod
    def _weighted_score(scores: dict, weights: dict, fallback: int) -> int:
        """按权重计算综合分；模型未给分时回退规则分。"""
        total = 0.0
        weight_sum = 0.0
        for key, weight in weights.items():
            if key not in scores:
                continue
            total += float(scores[key]) * float(weight)
            weight_sum += float(weight)
        if weight_sum <= 0:
            return fallback
        return max(0, min(100, int(total / weight_sum + 0.5)))

    @staticmethod
    def _verdict(
        score: int,
        rules: dict,
        pass_score: int,
        review_score: int,
        has_llm_issues: bool = False,
        llm_incomplete: bool = False,
    ) -> str:
        """综合规则与得分给出通过 / 复核 / 不通过。"""
        if rules.get("blocking") or score < review_score:
            return "fail"
        if score < pass_score or rules.get("issues") or has_llm_issues or llm_incomplete:
            return "review"
        return "pass"

    @staticmethod
    def _summary(llm: dict | None, rules: dict) -> str:
        """报告摘要：优先模型说明，其次规则结论。"""
        summary = str((llm or {}).get("summary") or "").strip()
        if summary:
            return summary
        stats = rules.get("stats") or {}
        if rules.get("blocking"):
            return "规则校验发现硬性错误，资源需修改后重新校验。"
        if stats.get("warnings"):
            return f"规则校验发现 {stats['warnings']} 项警告，建议教师复核后使用。"
        return "规则校验未发现明显问题。"

    @staticmethod
    def _suggestions(llm: dict | None, rules: dict) -> list[str]:
        """合并模型建议与规则建议，按原文去重。"""
        values = list((llm or {}).get("suggestions") or [])
        for issue in rules.get("issues") or []:
            suggestion = str(issue.get("suggestion") or "").strip()
            if suggestion:
                values.append(suggestion)
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result[:8]
