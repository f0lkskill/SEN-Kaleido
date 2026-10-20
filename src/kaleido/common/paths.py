"""项目路径定位。

默认使用项目根目录下的 ``configs/`` 与 ``data/``；
可通过环境变量 ``SEN_KALEIDO_CONFIG_DIR`` / ``SEN_KALEIDO_DATA_DIR`` 覆盖，
便于测试使用临时目录、部署时指向其它磁盘位置。
"""

import os
from pathlib import Path

# paths.py 位于 <root>/src/kaleido/common/paths.py，向上四级即项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(os.environ.get("SEN_KALEIDO_CONFIG_DIR", PROJECT_ROOT / "configs"))
DATA_DIR = Path(os.environ.get("SEN_KALEIDO_DATA_DIR", PROJECT_ROOT / "data"))
# 证据上传媒体目录（图像 / 视频 / 文本附件），与 JSON 文档库分离
EVIDENCE_MEDIA_DIR = Path(
    os.environ.get("SEN_KALEIDO_EVIDENCE_MEDIA_DIR", DATA_DIR / "evidence_files")
)
# 前端静态资源目录（HTML / CSS / JS 与后端脚本相互独立）
WEB_DIR = Path(os.environ.get("SEN_KALEIDO_WEB_DIR", PROJECT_ROOT / "src" / "web"))
