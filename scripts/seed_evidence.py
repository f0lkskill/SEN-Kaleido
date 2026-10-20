"""示例证据灌入脚本。

为证据管理页面准备可直接查看的示例数据，覆盖：
- 公有证据（未归类）：纯文本、图像、视频；
- 归类证据（已划分所有者）：文本、图像。

图像与视频样例放在 ``src/web/assets/samples``，通过前端静态路径访问。
运行：``python scripts/seed_evidence.py``
重复执行会按标题跳过已存在的示例，不会重复写入。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from kaleido.evidence.models import CreateEvidenceRequest, ReviewEvidenceRequest
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.profile.repository import StudentRepository
from kaleido.vault import Vault

SAMPLES = [
    {
        "scope": "public",
        "source_type": "classroom_observation",
        "media_type": "text",
        "title": "示例·课堂观察记录（纯文本）",
        "content": (
            "10:05 小组活动开始，学生主动举手两次。\n"
            "10:12 在教师提示下与同伴交换材料，并回应同伴提问。\n"
            "10:20 完成小组任务后主动整理桌面。"
        ),
        "collector": "示例教师",
        "note": "示例数据，可直接删除。",
    },
    {
        "scope": "public",
        "source_type": "image_capture",
        "media_type": "image",
        "title": "示例·学生绘画作品（图像）",
        "content": "暖色调绘画作品，画面包含房屋、树木与草地。",
        "attachments": ["/assets/samples/sample_evidence_image.svg"],
        "collector": "示例教师",
        "review": "verified",
    },
    {
        "scope": "public",
        "source_type": "video_event",
        "media_type": "video",
        "title": "示例·课堂互动片段（视频）",
        "content": "00:00-00:03 教师提问后，学生主动举手并作出回应。",
        "attachments": ["/assets/samples/sample_evidence_video.mp4"],
        "collector": "示例教师",
    },
    {
        "scope": "classified",
        "student_index": 0,
        "observation_key": "class_engagement",
        "source_type": "classroom_observation",
        "media_type": "text",
        "title": "示例·课堂参与观察（已归类）",
        "content": "小组活动中主动举手两次，并能回应同伴。",
        "collector": "示例教师",
        "review": "verified",
    },
    {
        "scope": "classified",
        "student_index": 1,
        "observation_key": "practice_completion",
        "source_type": "work_sample",
        "media_type": "image",
        "title": "示例·练习作品（已归类）",
        "content": "完成 8/10 题，书写清晰，图形题全部正确。",
        "attachments": ["/assets/samples/sample_evidence_image.svg"],
        "collector": "示例教师",
    },
]


def main() -> None:
    """写入示例证据；已存在的标题自动跳过。"""
    vault = Vault()
    students = StudentRepository(vault=vault)
    service = EvidenceService(
        repository=EvidenceRepository(vault=vault),
        student_repository=students,
    )
    existing = {
        str(item.get("title") or "")
        for item in service.list(size=1000)["items"]
    }
    student_items, _ = students.list(page=1, size=50)
    created = 0

    for sample in SAMPLES:
        title = sample["title"]
        if title in existing:
            print(f"跳过已存在：{title}")
            continue
        payload = dict(sample)
        review = payload.pop("review", None)
        student_index = payload.pop("student_index", None)
        if payload["scope"] == "classified":
            if student_index is None or student_index >= len(student_items):
                print(f"跳过（缺少学生档案）：{title}")
                continue
            payload["student_id"] = student_items[student_index]["profile_id"]
        try:
            record = service.create(CreateEvidenceRequest(**payload))
            if review:
                service.review(
                    record["evidence_id"],
                    ReviewEvidenceRequest(status=review, verified_by="示例教师"),
                )
            print(f"已写入 {record['evidence_id']} {title}")
            created += 1
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {title}: {exc}")

    print(f"完成，新增 {created} 条示例证据。")


if __name__ == "__main__":
    main()
