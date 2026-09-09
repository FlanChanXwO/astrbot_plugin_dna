"""运行期数据目录布局契约测试。"""

from __future__ import annotations

from pathlib import Path

from src.infrastructure import RuntimeDataLayout


def test_runtime_data_layout_exposes_new_production_paths_without_side_effects(
    tmp_path: Path,
) -> None:
    """构造布局只计算路径，不提前创建任何运行期目录。"""

    data_dir = tmp_path / "plugin-data"
    layout = RuntimeDataLayout(data_dir)

    assert layout.data_dir == data_dir
    assert layout.db_dir == data_dir / "db"
    assert layout.database_path == data_dir / "db" / "dna.sqlite3"
    assert layout.state_dir == data_dir / "state"
    assert layout.aliases_dir == data_dir / "state" / "aliases"
    assert layout.char_alias_path == data_dir / "state" / "aliases" / "char.json"
    assert layout.weapon_alias_path == data_dir / "state" / "aliases" / "weapon.json"
    assert layout.id2name_path == data_dir / "state" / "aliases" / "id2name.json"
    assert layout.resources_dir == data_dir / "resources"
    assert layout.cache_dir == data_dir / "cache"
    assert layout.backups_dir == data_dir / "backups"
    assert not data_dir.exists()


def test_runtime_data_layout_from_data_dir_accepts_string_path(
    tmp_path: Path,
) -> None:
    """工厂方法统一字符串路径，并保持同一布局契约。"""

    data_dir = tmp_path / "plugin-data"

    layout = RuntimeDataLayout.from_data_dir(str(data_dir))

    assert layout.data_dir == data_dir
    assert layout.database_path == data_dir / "db" / "dna.sqlite3"
