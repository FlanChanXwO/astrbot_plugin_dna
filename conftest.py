"""pytest 根配置：确保插件根目录可导入 ``dnaby``，且 AstrBot 不写插件目录。

- ``DNABY_DATA_DIR``：让 RESOURCE_PATH 指向临时数据目录。
- ``ASTRBOT_ROOT``：让 astrbot 的 get_astrbot_data_path() 指向临时根，避免在插件目录生成 data/。
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent

# 测试数据目录（gitignored，不入库）
os.environ.setdefault("DNABY_DATA_DIR", str(ROOT / "tests" / ".data"))
# AstrBot 根目录隔离，防止 astrbot 初始化在插件目录写 data/
os.environ.setdefault("ASTRBOT_ROOT", tempfile.mkdtemp(prefix="dnaby-astrbot-test-"))

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
