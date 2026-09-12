"""运行期数据目录布局契约测试。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure import RuntimeDataLayout
from src.infrastructure.cache import CacheManager
from src.infrastructure.config.settings import CacheSettings
from src.infrastructure.persistence import AsyncDatabase
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
    assert layout.subscriptions_path == data_dir / "state" / "subscriptions.json"
    assert layout.scheduler_state_path == data_dir / "state" / "scheduler.json"
    assert layout.announcements_dir == data_dir / "state" / "announcements"
    assert layout.ann_state_path == data_dir / "state" / "announcements" / "seen.json"
    assert layout.ann_delivery_state_path == (
        data_dir / "state" / "announcements" / "delivery.json"
    )
    assert layout.client_update_state_path == data_dir / "state" / "client_update.json"
    assert layout.aliases_dir == data_dir / "state" / "aliases"
    assert layout.char_alias_path == data_dir / "state" / "aliases" / "char.json"
    assert layout.weapon_alias_path == data_dir / "state" / "aliases" / "weapon.json"
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
    assert layout.backups_database_dir == data_dir / "backups" / "database"
    assert not data_dir.exists()


def test_runtime_data_layout_from_data_dir_accepts_string_path(
    tmp_path: Path,
) -> None:
    """工厂方法统一字符串路径，并保持同一布局契约。"""

    data_dir = tmp_path / "plugin-data"

    layout = RuntimeDataLayout.from_data_dir(str(data_dir))

    assert layout.data_dir == data_dir
    assert layout.database_path == data_dir / "db" / "dna.sqlite3"


def test_runtime_data_layout_exposes_cache_scopes_without_legacy_roots(
    tmp_path: Path,
) -> None:
    """动态素材、API、渲染和媒体缓存都落在 cache 下。"""

    data_dir = tmp_path / "plugin-data"
    layout = RuntimeDataLayout(data_dir)

    assert layout.cache_assets_dir == data_dir / "cache" / "assets"
    assert layout.cache_game_avatar_dir == data_dir / "cache" / "assets" / "game_avatar"
    assert layout.cache_user_avatar_dir == data_dir / "cache" / "assets" / "user_avatar"
    assert layout.cache_api_dir == data_dir / "cache" / "api"
    assert layout.cache_rendered_dir == data_dir / "cache" / "rendered"
    assert layout.cache_media_dir == data_dir / "cache" / "media"
    assert layout.cache_sign_dir == data_dir / "cache" / "media" / "sign"
    assert layout.cache_ann_card_dir == data_dir / "cache" / "media" / "ann_card"
    assert layout.cache_calendar_dir == data_dir / "cache" / "media" / "calendar"
    assert layout.cache_login_qr_dir == data_dir / "cache" / "media" / "login_qr"
    assert not data_dir.exists()


def test_resource_path_projection_uses_split_asset_and_media_scopes() -> None:
    """旧导入投影必须指向新 cache 分层，而不是顶层旧目录。"""

    from src.utils.resource.RESOURCE_PATH import (
        ANN_CARD_PATH,
        AVATAR_PATH,
        CALENDAR_PATH,
        LOGIN_QR_PATH,
        OTHER_PATH,
        RESOURCE_PATH,
        SIGN_PATH,
        USER_AVATAR_PATH,
    )

    layout = RuntimeDataLayout.from_data_dir(os.environ["DNABY_DATA_DIR"])

    assert RESOURCE_PATH == layout.cache_assets_dir
    assert AVATAR_PATH == layout.cache_game_avatar_dir
    assert USER_AVATAR_PATH == layout.cache_user_avatar_dir
    assert OTHER_PATH == layout.cache_media_dir
    assert SIGN_PATH == layout.cache_sign_dir
    assert ANN_CARD_PATH == layout.cache_ann_card_dir
    assert LOGIN_QR_PATH == layout.cache_login_qr_dir
    assert CALENDAR_PATH == layout.cache_calendar_dir


@pytest.mark.asyncio
async def test_cache_manager_partitions_typed_entries_and_keeps_cleanup_semantics(
    tmp_path: Path,
) -> None:
    """typed cache 的读写和 TTL 清理只改变物理分层，不改变语义。"""

    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    manager = CacheManager(
        layout.cache_dir,
        CacheSettings(ttl_hours=1),
        cache_type_roots={
            "player_data": layout.cache_api_dir,
            "player_card": layout.cache_rendered_dir,
            "mh": layout.cache_api_dir,
            "announcement": layout.cache_media_dir,
        },
    )
    created_at = datetime.now(timezone.utc)

    await manager.put("player_data", "player-key", b"{}", now=created_at)
    await manager.put("player_card", "card-key", b"card", now=created_at)
    await manager.put("mh", "mh-key", b"mh", now=created_at)
    await manager.put("announcement", "ann-key", b"ann", now=created_at)

    assert (layout.cache_api_dir / "player_data").is_dir()
    assert (layout.cache_api_dir / "mh").is_dir()
    assert (layout.cache_rendered_dir / "player_card").is_dir()
    assert (layout.cache_media_dir / "announcement").is_dir()
    assert (await manager.get("player_data", "player-key")).entry is not None
    assert (await manager.get("announcement", "ann-key")).entry is not None

    removed = await manager.cleanup(now=created_at + timedelta(hours=1))

    assert removed == 4
    assert not any(layout.cache_dir.rglob("*.data"))


@pytest.mark.asyncio
async def test_build_runtime_uses_cache_scopes_for_rendered_and_typed_cache(
    tmp_path: Path,
) -> None:
    """默认 runtime 不再把 rendered 或 typed cache 写到数据根。"""

    from src.bootstrap import build_runtime
    from src.utils import image_utils

    default_fetcher = image_utils.get_default_image_fetcher()
    layout = RuntimeDataLayout(tmp_path)
    database = AsyncDatabase(tmp_path / "dna.sqlite3")
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=database,
        runtime_data_layout=layout,
    )

    try:
        assert runtime.services["rendered_root"] == layout.cache_rendered_dir
        assert runtime.services["rendered_store"].root == layout.cache_rendered_dir
        assert runtime.services["cache_manager"].root == layout.cache_dir
        assert runtime.services["cache_manager"].cache_type_roots == {
            "player_data": layout.cache_api_dir,
            "player_card": layout.cache_rendered_dir,
            "mh": layout.cache_api_dir,
            "announcement": layout.cache_media_dir,
        }
        assert not (tmp_path / "rendered").exists()
        assert not (tmp_path / "resource").exists()
        assert not (tmp_path / "other").exists()

        asset_resolver = runtime.services["asset_resolver"]
        image_fetcher = runtime.services["image_fetcher"]
        assert asset_resolver.dynamic_root == layout.cache_assets_dir
        assert asset_resolver.coordinator is runtime.services["resource_snapshots"]
        assert asset_resolver.downloader is image_fetcher
        assert image_utils.get_default_image_fetcher() is default_fetcher
        assert image_fetcher is not default_fetcher
        assert runtime.lifecycle._start_hooks[0].__self__ is image_fetcher
        assert runtime.lifecycle._finalizer_hooks[0].__self__ is image_fetcher

        subscriptions = runtime.services["subscriptions"]
        assert subscriptions.path == layout.subscriptions_path
        scheduler_registry = runtime.services["scheduler_registry"]
        assert scheduler_registry.state_path == layout.scheduler_state_path
        notices_service = runtime.services["notices_service"]
        assert notices_service.ann_state.path == layout.ann_state_path
        assert notices_service.ann_delivery_state.path == layout.ann_delivery_state_path
        client_update_state = runtime.services["client_update_state"]
        assert client_update_state.path == layout.client_update_state_path

        for old_path in (
            tmp_path / "subscriptions.json",
            tmp_path / "scheduler_state.json",
            tmp_path / "ann_state.json",
            tmp_path / "ann_delivery_state.json",
            tmp_path / "client_update_state.json",
        ):
            assert not old_path.exists()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_build_runtime_uses_explicit_layout_for_injected_nested_database(
    tmp_path: Path,
) -> None:
    """注入 ``data/db/dna.sqlite3`` 时，运行期目录仍由显式 data root 决定。"""

    from src.bootstrap import build_runtime

    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase(layout.database_path)
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=database,
        runtime_data_layout=layout,
    )

    try:
        assert runtime.services["rendered_root"] == layout.cache_rendered_dir
        assert runtime.services["cache_manager"].root == layout.cache_dir
        assert runtime.services["subscriptions"].path == layout.subscriptions_path
        assert runtime.services["asset_resolver"].dynamic_root == (
            layout.cache_assets_dir
        )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_build_runtime_infers_only_standard_database_layout(
    tmp_path: Path,
) -> None:
    """标准 ``db/dna.sqlite3`` 路径仍可兼容推导 data root。"""

    from src.bootstrap import build_runtime

    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase(layout.database_path)
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=database,
    )

    try:
        assert runtime.services["rendered_root"] == layout.cache_rendered_dir
        assert runtime.services["subscriptions"].path == layout.subscriptions_path
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_build_runtime_requires_layout_for_nonstandard_injected_database(
    tmp_path: Path,
) -> None:
    """自定义注入数据库不能让 runtime 静默猜错数据根目录。"""

    from src.bootstrap import build_runtime

    database = AsyncDatabase(tmp_path / "custom.sqlite3")

    try:
        with pytest.raises(ValueError, match="runtime_data_layout"):
            build_runtime(
                SimpleNamespace(register_web_api=lambda *_args: None),
                {},
                database=database,
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_build_runtime_allocates_image_fetcher_per_runtime(
    tmp_path: Path,
) -> None:
    """每个 runtime 拥有自己的共享图片下载器，避免跨事件循环复用 client。"""

    from src.bootstrap import build_runtime
    from src.utils import image_utils

    default_fetcher = image_utils.get_default_image_fetcher()
    first_layout = RuntimeDataLayout(tmp_path / "first-data")
    second_layout = RuntimeDataLayout(tmp_path / "second-data")
    first_database = AsyncDatabase(tmp_path / "first.sqlite3")
    second_database = AsyncDatabase(tmp_path / "second.sqlite3")
    first_runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=first_database,
        runtime_data_layout=first_layout,
    )
    second_runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=second_database,
        runtime_data_layout=second_layout,
    )

    try:
        first_fetcher = first_runtime.services["image_fetcher"]
        second_fetcher = second_runtime.services["image_fetcher"]

        assert first_fetcher is not second_fetcher
        assert image_utils.get_default_image_fetcher() is default_fetcher
        assert first_fetcher is not default_fetcher
        assert second_fetcher is not default_fetcher
    finally:
        await first_database.dispose()
        await second_database.dispose()


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
