"""统一日志工具。

为 ``kaleido`` 包提供统一的日志格式与 handler（终端 + 本地文件轮转），
方便在基站上事后排查问题；第三方库与用户脚本的日志互不干扰。
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from kaleido.common.paths import PROJECT_ROOT

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False
LOG_DIR = PROJECT_ROOT / "logs"


def _resolve_level() -> int:
    """从环境变量 ``SEN_KALEIDO_LOG_LEVEL`` 解析日志级别（默认 INFO）。"""
    name = os.environ.get("SEN_KALEIDO_LOG_LEVEL", "INFO").upper()
    return getattr(logging, name, logging.INFO)


def _configure_root() -> None:
    """首次调用时为 kaleido 根 logger 挂载 handler（幂等）。"""
    global _configured
    if _configured:
        return
    formatter = logging.Formatter(_FORMAT)
    root = logging.getLogger("kaleido")
    root.setLevel(_resolve_level())

    # 终端输出：开发/前台运行时可直接观察
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # 本地文件输出：轮转保留，便于事后排查
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / "kaleido.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # 磁盘只读或权限异常时仅保留终端输出，不影响主流程
        pass

    # 不向全局 root 传播，避免污染调用方日志
    root.propagate = False
    _configured = True


def setup_logging(level: str | None = None) -> None:
    """显式初始化日志系统（幂等）。

    :param level: 覆盖日志级别（如 ``"DEBUG"``）；缺省用环境变量
        ``SEN_KALEIDO_LOG_LEVEL``，再缺省 INFO。
    """
    _configure_root()
    if level:
        logging.getLogger("kaleido").setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """获取带 ``kaleido.`` 前缀的 logger。"""
    _configure_root()
    return logging.getLogger(name if name.startswith("kaleido") else f"kaleido.{name}")
