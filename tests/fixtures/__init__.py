"""本地测试集加载工具。

统一从 ``tests/fixtures/`` 读取样例数据，供单元、对接与端到端测试复用。
"""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def load_student_samples() -> dict:
    """加载学生样例集（valid 覆盖矩阵，edge 覆盖边界与非法输入）。"""
    path = FIXTURES_DIR / "students" / "samples.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fixtures_path(*parts: str) -> Path:
    """拼接 fixtures 下的路径。"""
    return FIXTURES_DIR.joinpath(*parts)
