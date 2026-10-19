"""闲时判定：决定是否处于云端定价的"谷段"。

DeepSeek 等云端模型采用峰谷定价，闲时（夜间、周末、法定节假日）价格
为高峰时段的一半。批量任务可通过 ``defer_off_peak`` 标记，仅在闲时执行。
"""

from datetime import datetime
from datetime import time as dtime


def _parse_time(value: str) -> dtime:
    """把 ``"HH:MM"`` 解析为 time；非法时抛 ValueError。"""
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


def _in_window(now_time: dtime, start: dtime, end: dtime) -> bool:
    """判断当前时刻是否落在 [start, end) 区间内，支持跨零点。"""
    if start <= end:
        return start <= now_time < end
    # 跨零点窗口，如 22:00 - 07:00
    return now_time >= start or now_time < end


def is_off_peak(now: datetime, config: dict | None = None) -> bool:
    """判断给定时刻是否属于闲时。

    :param now: 待判定的时间
    :param config: ``configs/tasks/tasks.yaml`` 的 ``schedule`` 片段；
                   为空时回退为"所有时段均非闲时"，保证默认行为一致。
    """
    schedule = (config or {}).get("off_peak", {})
    if not schedule:
        return False

    # 法定节假日整天记为闲时
    holidays = schedule.get("holidays") or []
    if now.strftime("%Y-%m-%d") in holidays:
        return True

    # 周末整天记为闲时（weekday: 周一=0 ... 周日=6）
    if schedule.get("weekends", False) and now.weekday() >= 5:
        return True

    # 逐一时段判断
    for window in schedule.get("windows", []):
        try:
            start = _parse_time(str(window.get("start", "00:00")))
            end = _parse_time(str(window.get("end", "00:00")))
        except (ValueError, AttributeError):
            continue
        if _in_window(now.time(), start, end):
            return True

    return False
