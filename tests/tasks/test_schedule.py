"""闲时判定测试：时段、周末与节假日。"""

import sys
from datetime import datetime
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.tasks.schedule import is_off_peak

# 覆盖跨零点窗口（夜间）的配置
CONFIG = {
    "off_peak": {
        "weekends": True,
        "holidays": ["2026-10-01"],
        "windows": [{"start": "22:00", "end": "07:00"}],
    }
}

# 2026-10-05 是周一（工作日）
MONDAY_PEAK = datetime(2026, 10, 5, 15, 0)
MONDAY_NIGHT = datetime(2026, 10, 5, 23, 30)
MONDAY_EARLY = datetime(2026, 10, 5, 6, 0)
SATURDAY = datetime(2026, 10, 3, 15, 0)


def test_no_config_defaults_to_peak():
    """未配置闲时时段时，任何时刻都不算闲时。"""
    assert is_off_peak(MONDAY_NIGHT, {}) is False
    assert is_off_peak(MONDAY_NIGHT, None) is False


def test_peak_hours_are_not_off_peak():
    """工作日白天属于高峰。"""
    assert is_off_peak(MONDAY_PEAK, CONFIG) is False


def test_cross_midnight_window():
    """跨零点的夜间窗口：22:00 之后与 07:00 之前均为闲时。"""
    assert is_off_peak(MONDAY_NIGHT, CONFIG) is True
    assert is_off_peak(MONDAY_EARLY, CONFIG) is True


def test_weekend_is_off_peak():
    """周六全天视为闲时。"""
    assert is_off_peak(SATURDAY, CONFIG) is True


def test_holiday_is_off_peak():
    """法定节假日全天视为闲时。"""
    holiday = datetime(2026, 10, 1, 15, 0)  # 周四
    assert is_off_peak(holiday, CONFIG) is True


def test_weekend_disabled():
    """关闭周末闲时开关后，周末白天不再算闲时。"""
    config = {"off_peak": {"weekends": False, "windows": [{"start": "22:00", "end": "07:00"}]}}
    assert is_off_peak(SATURDAY, config) is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
