"""本地联调数据灌入脚本。

把 ``tests/fixtures/students/samples.json`` 的合法样例写入真实 ``data/``
（经 ProfileService），便于前端与下游模块本地联调。
运行：``python scripts/seed_data.py``
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.service import ProfileService
from tests.fixtures import load_student_samples


def main() -> None:
    """遍历合法样例建档，重复的请求 ID 会被跳过。"""
    service = ProfileService()
    for index, sample in enumerate(load_student_samples()["valid"], start=1):
        request = CreateStudentRequest(
            client_request_id=f"seed-{index}",
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
