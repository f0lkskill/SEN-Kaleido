"""pytest 全局配置。

在未安装项目（``pip install -e .``）时也能从源码树导入 ``kaleido``，
保证 ``pytest`` 与直接运行测试文件都可用。
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
