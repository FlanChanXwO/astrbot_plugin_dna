"""旧版运行期数据布局检测与启动门禁测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure import (
    LegacyLayoutDetector,
    LegacyLayoutError,
    RuntimeDataLayout,
)

LEGACY_PATHS = (
    "dnaby.sqlite3",
    "dnaby.db",
    "resource",
    "resource_generations",
    "rendered",
    "other",
    "custom",
    "players",
    "subscriptions.json",
    "scheduler_state.json",
    "ann_state.json",
    "ann_delivery_state.json",
    "client_update_state.json",
    "alias_custom.json",
    "weapon_alias_custom.json",
    "config.json",
    "sign_config.json",
    "resources/.git",
    "cache/player_data",
)


def _create_legacy_path(data_dir: Path, relative_path: str) -> None:
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix in {".db", ".sqlite3", ".json"}:
        path.write_text("legacy", encoding="utf-8")
    else:
        path.mkdir()
        if relative_path != "resources/.git":
            (path / "marker.txt").write_text("legacy", encoding="utf-8")


@pytest.mark.parametrize("relative_path", LEGACY_PATHS)
def test_legacy_layout_detector_reports_each_known_old_path(
    tmp_path: Path,
    relative_path: str,
) -> None:
    """已知旧路径被报告，检测过程不创建新布局目录。"""

    data_dir = tmp_path / "plugin-data"
    _create_legacy_path(data_dir, relative_path)
    layout = RuntimeDataLayout(data_dir)

    issues = LegacyLayoutDetector(layout).detect()

    assert [issue.relative_path for issue in issues] == [relative_path]
    assert not layout.db_dir.exists()
    assert not layout.state_dir.exists()
    assert not layout.cache_dir.exists() or relative_path.startswith("cache/")



def test_legacy_layout_detector_allows_new_resource_repository_marker(
    tmp_path: Path,
) -> None:
    """新资源仓库位于 resources/repository，不被旧 resources/.git 规则误报。"""

    data_dir = tmp_path / "plugin-data"
    (data_dir / "resources" / "repository" / ".git").mkdir(parents=True)

    issues = LegacyLayoutDetector(RuntimeDataLayout(data_dir)).detect()

    assert issues == ()



def test_legacy_layout_detector_allows_empty_new_layout_directories(
    tmp_path: Path,
) -> None:
    """新布局的空目录以及新资源仓库不会触发旧布局门禁。"""

    data_dir = tmp_path / "plugin-data"
    layout = RuntimeDataLayout(data_dir)
    for directory in (
        layout.db_dir,
        layout.state_dir,
        layout.resources_dir,
        layout.cache_dir,
        layout.backups_dir,
    ):
        directory.mkdir(parents=True)
    (layout.resources_dir / "repository" / ".git").mkdir(parents=True)

    assert LegacyLayoutDetector(layout).detect() == ()


def test_legacy_layout_detector_raises_migration_error_without_mutating_data(
    tmp_path: Path,
) -> None:
    """发现旧布局时只抛出人工迁移错误，不复制或移动任何数据。"""

    data_dir = tmp_path / "plugin-data"
    legacy_path = data_dir / "resource"
    legacy_path.mkdir(parents=True)
    marker = legacy_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(LegacyLayoutError) as caught:
        LegacyLayoutDetector(RuntimeDataLayout(data_dir)).ensure_compatible()

    assert "resource" in str(caught.value)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (data_dir / "db").exists()



def test_build_runtime_rejects_legacy_layout_before_database_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """真实 runtime 构造在创建数据库前拒绝旧数据布局。"""

    data_dir = tmp_path / "plugin-data"
    data_dir.mkdir()
    (data_dir / "dnaby.db").write_bytes(b"legacy")

    from astrbot.api.star import StarTools

    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    monkeypatch.setattr(StarTools, "get_data_dir", lambda _plugin_name: data_dir)
    database_factory_called = False

    def unexpected_database_factory(cls, *args, **kwargs):
        del cls, args, kwargs
        nonlocal database_factory_called
        database_factory_called = True
        raise AssertionError("legacy detector must run before database creation")

    monkeypatch.setattr(
        AsyncDatabase,
        "from_data_dir",
        classmethod(unexpected_database_factory),
    )

    with pytest.raises(LegacyLayoutError):
        build_runtime(SimpleNamespace(), {})

    assert database_factory_called is False
    assert not (data_dir / "db").exists()
