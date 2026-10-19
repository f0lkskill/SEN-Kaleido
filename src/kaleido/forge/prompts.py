"""分层 Prompt 模板加载与渲染。

模板存放在项目根目录 ``prompts/<template_key>.txt``，使用 ``{placeholder}``
占位；缺失字段渲染为空字符串，避免因个别属性缺省导致渲染失败。
"""

from functools import cache

from kaleido.common.errors import ConfigError
from kaleido.common.paths import PROJECT_ROOT

PROMPTS_DIR = PROJECT_ROOT / "prompts"


class _SafeDict(dict):
    """缺失键返回空字符串，保证 format_map 不抛 KeyError。"""

    def __missing__(self, key: str) -> str:
        return ""


@cache
def load_template(template_key: str) -> str:
    """按模板键读取模板文本（带缓存）。"""
    path = PROMPTS_DIR / f"{template_key}.txt"
    if not path.exists():
        raise ConfigError(f"Prompt 模板不存在: {path}")
    return path.read_text(encoding="utf-8")


def render(template_key: str, mapping: dict) -> str:
    """渲染模板。"""
    return load_template(template_key).format_map(_SafeDict(mapping))
