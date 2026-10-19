"""配置加载器。

读取 ``configs/profile`` 下的 YAML 配置，带进程内缓存（避免重复 IO），
并提供 :func:`reload_config` 支持试点期间热重载调参。
"""

from pathlib import Path
from threading import RLock

import yaml

from kaleido.common.errors import ConfigError
from kaleido.common.paths import CONFIG_DIR

# 读缓存与写保护锁，保证多线程下配置只加载一次
_lock = RLock()
_cache: dict[str, dict] = {}


def _read_yaml(path: Path) -> dict:
    """读取并解析单个 YAML 文件，失败时抛出 ConfigError。"""
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件解析失败: {path}: {exc}") from exc
    # 顶层必须是映射结构，否则视为非法配置
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件内容非法: {path}")
    return data


def load_config(name: str, subdir: str = "profile") -> dict:
    """加载 ``configs/<subdir>/<name>.yaml``，带缓存。"""
    cache_key = f"{subdir}/{name}"
    with _lock:
        if cache_key not in _cache:
            _cache[cache_key] = _read_yaml(CONFIG_DIR / subdir / f"{name}.yaml")
        return _cache[cache_key]


def load_rubric(name: str) -> dict:
    """加载评分标准 ``configs/profile/rubrics/<name>.yaml``，带缓存。"""
    cache_key = f"profile/rubrics/{name}"
    with _lock:
        if cache_key not in _cache:
            _cache[cache_key] = _read_yaml(CONFIG_DIR / "profile" / "rubrics" / f"{name}.yaml")
        return _cache[cache_key]


def reload_config() -> None:
    """清空配置缓存，使下次读取重新加载文件。"""
    with _lock:
        _cache.clear()
