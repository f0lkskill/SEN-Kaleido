"""统一日志工具。

为 ``kaleido`` 包提供统一的日志格式与 handler，避免各模块重复配置；
第三方库与用户脚本的日志互不干扰。
"""

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def _configure_root() -> None:
    """首次调用时为 kaleido 根 logger 挂载 handler（幂等）。"""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger("kaleido")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # 不向全局 root 传播，避免污染调用方日志
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带 ``kaleido.`` 前缀的 logger。"""
    _configure_root()
    return logging.getLogger(name if name.startswith("kaleido") else f"kaleido.{name}")
