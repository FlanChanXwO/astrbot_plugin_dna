"""运行期数据目录布局契约测试。"""

from __future__ import annotations

from pathlib import Path

from src.infrastructure import RuntimeDataLayout
from src.infrastructure.resources import (
    resource_generation_state_path,
    resource_generations_dir,
    resource_last_sync_state_path,
    resource_repository_dir,
    resource_validation_state_path,
)


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
    assert layout.resource_repository_dir == data_dir / "resources" / "repository"
    assert layout.resource_generations_dir == data_dir / "resources" / "generations"
    assert layout.resource_generation_state_path == (
        data_dir / "resources" / "generations" / "current.json"
    )
    assert layout.resource_last_sync_state_path == (
        data_dir / "resources" / "generations" / "last_sync.json"
    )
    assert layout.resource_validation_state_path == (
        data_dir / "resources" / "generations" / "validation.json"
    )
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


def test_resource_path_helpers_use_nested_resource_layout(tmp_path: Path) -> None:
    """资源路径 helper 与 RuntimeDataLayout 使用同一嵌套目录契约。"""

    data_dir = tmp_path / "plugin-data"
    assert resource_repository_dir(data_dir) == data_dir / "resources" / "repository"
    assert resource_generations_dir(data_dir) == data_dir / "resources" / "generations"
    assert resource_generation_state_path(data_dir) == (
        data_dir / "resources" / "generations" / "current.json"
    )
    assert resource_last_sync_state_path(data_dir) == (
        data_dir / "resources" / "generations" / "last_sync.json"
    )
    assert resource_validation_state_path(data_dir) == (
        data_dir / "resources" / "generations" / "validation.json"
    )
    assert not data_dir.exists()
