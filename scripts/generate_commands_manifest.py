"""从 v0.1 代码 registry 生成根目录 commands.json。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    """生成提交到仓库的命令 manifest。"""

    from src.entry.commands import load_command_registry, write_command_manifest

    write_command_manifest(PROJECT_ROOT / "commands.json", load_command_registry())


if __name__ == "__main__":
    main()
