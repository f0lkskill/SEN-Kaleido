"""本地联调数据灌入脚本。

把 ``tests/fixtures/students/demo_students.json`` 中的真实感演示数据
（含多障碍学生）经 :class:`ProfileService` 写入真实 ``data/``，
便于前端与下游模块本地联调。
运行：``python scripts/seed_data.py``
"""

import json
import sys
from pathlib import Path

# 直接运行本脚本时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.service import ProfileService

# 演示数据文件：真实感姓名 + 合理属性组合，覆盖多障碍情形
DEMO_FILE = ROOT / "tests" / "fixtures" / "students" / "demo_students.json"


def main() -> None:
    """遍历演示数据建档，重复的请求 ID 会被跳过（幂等）。"""
    students = json.loads(DEMO_FILE.read_text(encoding="utf-8"))["students"]
    service = ProfileService()
    for index, sample in enumerate(students, start=1):
        request = CreateStudentRequest(
            client_request_id=f"demo-{index}",
            name=sample["name"],
            attributes=StudentAttributesInput(**sample["attributes"]),
        )
        try:
            profile = service.create_student(request)
            print(f"已建档 {profile['profile_id']} {profile['name']}")
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {sample['name']}: {exc}")


if __name__ == "__main__":
    main()
