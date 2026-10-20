"""把耗时业务登记为任务面板可见的记录。

HTTP 同步接口（如资源生成、质量校验、画像分析）不经过后台队列，
但教师仍需要从任务面板看到这些模型分析的执行过程与结果。本模块
提供统一的登记与状态收尾逻辑，避免各模块重复实现。
"""

from collections.abc import Callable, Iterator
from typing import Any

from kaleido.tasks.service import TaskService


def task_summary(result: Any) -> dict:
    """提取任务面板需要的精简结果，避免整篇正文塞进任务记录。"""
    if not isinstance(result, dict):
        return {"value": result}
    summary = {
        key: result[key]
        for key in (
            "resource_id",
            "profile_id",
            "model",
            "status",
            "prompt_template_key",
            "verdict",
            "score",
            "snapshot_id",
            "period",
            "coverage",
            "dimension_scores",
            "missing_observations",
            "evidence_count",
            "computed_at",
            "overall_score",
            "rule_score",
            "blocking",
            "dimensions",
            "issues",
            "suggestions",
            "strengths",
        )
        if key in result
    }
    content = result.get("content")
    if isinstance(content, str) and content:
        limit = 12000
        summary["content"] = content[:limit]
        summary["content_truncated"] = len(content) > limit
    quality = result.get("quality")
    if isinstance(quality, dict):
        summary["quality"] = {
            "ok": quality.get("ok"),
            "score": quality.get("score"),
            "issues": len(quality.get("issues") or []),
        }
    text = result.get("summary")
    if isinstance(text, str) and len(text) <= 200:
        summary["summary"] = text
    # 画像分析返回 {profile, portrait}，补上学生 ID 便于任务面板定位
    profile = result.get("profile")
    if isinstance(profile, dict) and profile.get("profile_id"):
        summary.setdefault("profile_id", profile["profile_id"])
    return summary or {"keys": sorted(result)}


def record_task(
    task_service: TaskService | None,
    task_type: str,
    payload: dict,
    action: Callable[[], Any],
) -> Any:
    """执行同步业务并把整个过程登记为任务记录。

    ``task_service`` 为空时直接执行，便于单元测试或纯模块部署。
    业务异常会在任务标记失败后原样抛出，由 API 层统一映射响应。
    """
    if task_service is None:
        return action()
    task = task_service.create_external(task_type, payload)
    task_id = task["task_id"]
    task_service.mark_running(task_id)
    try:
        result = action()
    except Exception as exc:
        task_service.mark_failed(task_id, str(exc))
        raise
    task_service.mark_succeeded(task_id, task_summary(result))
    return result


def record_stream(
    task_service: TaskService | None,
    task_type: str,
    payload: dict,
    events: Iterator[dict],
) -> Iterator[dict]:
    """给流式业务套一层任务生命周期记录。"""
    if task_service is None:
        yield from events
        return
    task = task_service.create_external(task_type, payload)
    task_id = task["task_id"]
    task_service.mark_running(task_id)
    content_parts: list[str] = []
    finished = False
    try:
        for event in events:
            event_type = event.get("type")
            if event_type == "content":
                content_parts.append(str(event.get("text") or ""))
            elif event_type == "done":
                result = dict(event)
                if content_parts and not result.get("content"):
                    result["content"] = "".join(content_parts)
                task_service.mark_succeeded(task_id, task_summary(result))
                finished = True
            elif event_type == "error":
                task_service.mark_failed(
                    task_id, str(event.get("message") or "执行失败")
                )
                finished = True
            yield event
    finally:
        if not finished:
            task_service.mark_failed(task_id, "执行流提前结束或连接中断")
