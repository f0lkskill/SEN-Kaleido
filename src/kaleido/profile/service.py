"""业务服务层。

组合类型层、属性层、评价框架层与仓库，对外提供用例级接口：
建档、查询、列表、更新、删除、框架预览与元数据查询。
API 层与脚本都只依赖本层，不直接操作配置与存储。
"""

import hashlib
from datetime import datetime

from kaleido.common.errors import ConflictError, NotFoundError, ValidationError
from kaleido.common.logging import get_logger
from kaleido.profile.attributes import AttributeSchema
from kaleido.profile.config_loader import load_config, load_rubric, reload_config
from kaleido.profile.framework import FrameworkEngine
from kaleido.profile.models.evaluation import (
    GenerationPrompt,
    StudentEvaluationProfile,
    StudentPortrait,
)
from kaleido.profile.models.student import (
    CreateStudentRequest,
    StudentAttributesInput,
    UpdateStudentRequest,
)
from kaleido.profile.repository import StudentRepository
from kaleido.profile.taxonomy import Taxonomy

# 带时区的时间格式，便于跨设备统一展示
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

logger = get_logger("profile.service")


def _now() -> str:
    """当前本地时间字符串。"""
    return datetime.now().astimezone().strftime(_TIME_FORMAT)


class ProfileService:
    """学生评价画像业务服务。"""

    def __init__(self, repository=None, taxonomy=None, schema=None, engine=None):
        # 依赖可注入，便于测试替换（如指向临时目录的仓库）
        self.repository = repository or StudentRepository()
        self.taxonomy = taxonomy or Taxonomy.load()
        self.schema = schema or AttributeSchema.load()
        self.engine = engine or FrameworkEngine.load()

    def create_student(self, request: CreateStudentRequest) -> dict:
        """建档：幂等校验 → 属性解析 → 生成评价框架 → 持久化。"""
        if self.repository.find_by_request(request.client_request_id):
            raise ConflictError(f"client_request_id 重复: {request.client_request_id}")
        attributes = self.schema.resolve(self.taxonomy, request.attributes)
        profile_id = self.repository.next_id()
        framework = self.engine.build(
            attributes.disabilities[0],
            attributes.severity,
            attributes.cognitive_level,
            attributes.learning_pace,
            attributes.rehab_goals,
            f"fw_{profile_id}",
        )
        now = _now()
        profile = StudentEvaluationProfile(
            profile_id=profile_id,
            name=request.name,
            attributes=attributes,
            framework=framework,
            created_at=now,
            updated_at=now,
        )
        self.repository.save(profile, request.client_request_id)
        logger.info(
            "建立档案: id=%s name=%s disabilities=%s cognitive=%s",
            profile_id,
            request.name,
            attributes.disabilities,
            attributes.cognitive_level,
        )
        return profile.model_dump()

    def get_student(self, profile_id: str) -> dict:
        """获取单个学生档案。"""
        return self.repository.get(profile_id).model_dump()

    def list_students(
        self,
        disability: str | None = None,
        cognitive_level: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按条件分页列出学生档案。"""
        items, total = self.repository.list(disability, cognitive_level, page, size)
        return {"total": total, "page": page, "size": size, "items": items}

    def update_student(self, profile_id: str, request: UpdateStudentRequest) -> dict:
        """更新档案；若属性变更则重新生成评价框架。"""
        profile = self.repository.get(profile_id)
        if request.name is not None:
            profile.name = request.name
        if request.attributes is not None:
            attributes = self.schema.resolve(self.taxonomy, request.attributes)
            profile.attributes = attributes
            profile.framework = self.engine.build(
                attributes.disabilities[0],
                attributes.severity,
                attributes.cognitive_level,
                attributes.learning_pace,
                attributes.rehab_goals,
                f"fw_{profile_id}",
            )
        profile.updated_at = _now()
        self.repository.save(profile)
        logger.info("更新档案: id=%s", profile_id)
        return profile.model_dump()

    def delete_student(self, profile_id: str) -> dict:
        """删除档案。"""
        self.repository.delete(profile_id)
        logger.info("删除档案: id=%s", profile_id)
        return {"profile_id": profile_id}

    def save_portrait(self, profile_id: str, portrait: dict) -> dict:
        """保存证据分析生成的学生画像，并刷新档案更新时间。"""
        profile = self.repository.get(profile_id)
        profile.portrait = StudentPortrait(**portrait)
        profile.updated_at = _now()
        self.repository.save(profile)
        logger.info("保存学生画像: id=%s model=%s", profile_id, profile.portrait.model)
        return profile.model_dump()

    def get_prompt_board(self, profile_id: str) -> list[dict]:
        """读取画像下方的生成提示词规则板。"""
        profile = self.repository.get(profile_id)
        return [item.model_dump() for item in profile.prompt_board]

    def add_prompt_board_items(self, profile_id: str, items: list[dict]) -> list[dict]:
        """把质量校验提炼的提示词追加到规则板（按文本去重）。"""
        profile = self.repository.get(profile_id)
        existing = {item.text.strip() for item in profile.prompt_board}
        now = _now()
        added = 0
        for raw in items:
            text = str(raw.get("text") or raw.get("prompt") or "").strip()
            if not text or text in existing:
                continue
            digest = hashlib.sha1(f"{profile_id}:{text}".encode()).hexdigest()[:10]
            profile.prompt_board.append(
                GenerationPrompt(
                    prompt_id=f"pb_{digest}",
                    text=text,
                    source_resource_id=raw.get("source_resource_id"),
                    source_topic=str(raw.get("source_topic") or ""),
                    source_score=raw.get("source_score"),
                    model=str(raw.get("model") or ""),
                    created_at=now,
                )
            )
            existing.add(text)
            added += 1
        if added:
            # 规则板只保留最近 50 条，避免档案无限膨胀
            profile.prompt_board = profile.prompt_board[-50:]
            profile.updated_at = now
            self.repository.save(profile)
            logger.info("规则板新增提示词: id=%s count=%d", profile_id, added)
        return [item.model_dump() for item in profile.prompt_board]

    def add_prompt_board_item(self, profile_id: str, text: str, title: str = "") -> list[dict]:
        """手动新增一条生成提示词。"""
        content = str(text or "").strip()
        if not content:
            raise ValidationError("提示词内容不能为空")
        if title:
            content = f"{str(title).strip()}：{content}"
        return self.add_prompt_board_items(profile_id, [{"text": content}])

    def update_prompt_board_item(
        self,
        profile_id: str,
        prompt_id: str,
        text: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict]:
        """修改提示词文本或启用状态。"""
        profile = self.repository.get(profile_id)
        target = next(
            (item for item in profile.prompt_board if item.prompt_id == prompt_id),
            None,
        )
        if target is None:
            raise NotFoundError(f"提示词不存在: {prompt_id}")
        if text is not None:
            content = str(text).strip()
            if not content:
                raise ValidationError("提示词内容不能为空")
            if any(
                item.text.strip() == content and item.prompt_id != prompt_id
                for item in profile.prompt_board
            ):
                raise ConflictError("规则板中已存在相同提示词")
            target.text = content
        if enabled is not None:
            target.enabled = bool(enabled)
        profile.updated_at = _now()
        self.repository.save(profile)
        logger.info("规则板更新提示词: id=%s prompt=%s", profile_id, prompt_id)
        return [item.model_dump() for item in profile.prompt_board]

    def delete_prompt_board_item(self, profile_id: str, prompt_id: str) -> list[dict]:
        """删除规则板中的提示词。"""
        profile = self.repository.get(profile_id)
        remaining = [item for item in profile.prompt_board if item.prompt_id != prompt_id]
        if len(remaining) == len(profile.prompt_board):
            raise NotFoundError(f"提示词不存在: {prompt_id}")
        profile.prompt_board = remaining
        profile.updated_at = _now()
        self.repository.save(profile)
        logger.info("规则板删除提示词: id=%s prompt=%s", profile_id, prompt_id)
        return [item.model_dump() for item in profile.prompt_board]

    def preview_framework(self, attributes: StudentAttributesInput) -> dict:
        """仅预览属性解析与框架生成结果，不落库。"""
        resolved = self.schema.resolve(self.taxonomy, attributes)
        framework = self.engine.build(
            resolved.disabilities[0],
            resolved.severity,
            resolved.cognitive_level,
            resolved.learning_pace,
            resolved.rehab_goals,
            "fw_preview",
        )
        return {"attributes": resolved.model_dump(), "framework": framework.model_dump()}

    def get_dimensions(self) -> dict:
        """返回评价维度定义与基础权重。"""
        config = load_config("evaluation_frameworks")
        return {
            "dimensions": config.get("dimensions", {}),
            "base_weights": config.get("base_weights", {}),
        }

    def get_rubric(self, key: str) -> dict:
        """返回指定评分标准。"""
        return load_rubric(key)

    def get_evidence_sources(self) -> dict:
        """返回证据来源类型定义。"""
        return load_config("evidence_sources").get("evidence_sources", {})

    def list_types(self) -> list[dict]:
        """返回全部学生类型定义。"""
        return [student_type.model_dump() for student_type in self.taxonomy.all()]

    def reload(self) -> dict:
        """热重载全部配置（试点调参用）。"""
        reload_config()
        self.taxonomy = Taxonomy.load()
        self.schema = AttributeSchema.load()
        self.engine = FrameworkEngine.load()
        logger.info("热重载配置完成")
        return {"student_types": self.taxonomy.keys()}
