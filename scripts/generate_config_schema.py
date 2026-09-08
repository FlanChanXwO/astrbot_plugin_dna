"""从 ``src.infrastructure.config`` 生成插件根目录 schema。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """生成提交到仓库的 AstrBot 配置 schema。"""

    from src.infrastructure.config import write_astrbot_schema

    write_astrbot_schema(ROOT / "_conf_schema.json")


if __name__ == "__main__":
    main()
