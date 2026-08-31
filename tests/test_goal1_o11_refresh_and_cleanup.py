"""O11 角色刷新命令、角色缓存清理和 rendered 租约测试。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PIL import Image

from src.entry.commands import CommandRegistry, CommandRequest, load_command_registry
from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse, ResponseFactory
from src.infrastructure.cache import CacheMaintenance
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.rendering import RenderedFileStore
from src.modules.player import messages
from src.modules.player.commands import (
    REFRESH_ADMIN_ROLE_PATTERN,
    REFRESH_ROLE_PATTERN,
    player_clear_all_cache_use_case,
    player_refresh_admin_role_use_case,
    player_refresh_role_use_case,
)
from tests.test_goal1_o10_player_cache import (
    MutableClock,
    _request,
    _service,
)


def test_o11_commands_are_registered_with_the_declared_permission_boundary() -> None:
    registry = load_command_registry()
    specs = {spec.id: spec for spec in registry}

    assert specs["refresh_role_card"].permission == "user"
    assert specs["refresh_admin_role_card"].permission == "admin"
    assert specs["clear_player_cache"].permission == "user"
    assert specs["refresh_role_card"].pattern == rf"^kk{REFRESH_ROLE_PATTERN[1:]}"
    assert specs["refresh_admin_role_card"].pattern == rf"^kk{REFRESH_ADMIN_ROLE_PATTERN[1:]}"
    assert registry.match("kk刷新角色甲面板").command.id == "refresh_role_card"
    assert registry.match("kk刷新123456的角色甲面板").command.id == "refresh_admin_role_card"
    assert registry.match("kk清理全部角色缓存").command.id == "clear_player_cache"


def test_zero_fresh_ttl_uses_retention_period_for_maintenance_cadence(
    tmp_path: Path,
) -> None:
    """立即 stale 配置不能让后台维护进入零秒忙循环或阻止 bootstrap。"""

    from src.bootstrap import build_runtime

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {"cache": {"fresh_ttl_minutes": 0}},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )
    maintenance = cast(CacheMaintenance, runtime.services["cache_maintenance"])

    assert maintenance.interval_seconds == 24 * 60 * 60


def test_bootstrap_wires_refresh_setting_and_cache_maintenance(
    tmp_path: Path,
) -> None:
    """bootstrap 必须把刷新开关和同一组缓存维护依赖交给 runtime。"""

    from src.bootstrap import build_runtime
    from src.modules.player.service import PlayerService

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {"cache": {"refresh_send_card": False}},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )
    player_service = cast(PlayerService, runtime.services["player_service"])
    cache_manager = runtime.services["cache_manager"]
    rendered_store = runtime.services["rendered_store"]
    maintenance = cast(CacheMaintenance, runtime.services["cache_maintenance"])

    assert player_service.refresh_send_card is False
    assert maintenance.manager is cache_manager
    assert maintenance.rendered is rendered_store


@pytest.mark.asyncio
async def test_user_refresh_forces_target_role_and_keeps_other_role_cache(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    database, transport, renderer, cache, service = await _service(tmp_path, clock)
    try:
        first = await service.role_detail(_request(detail=True))
        assert isinstance(first, ImageResponse)
        identity = cache.identity_tag("user-1", "1234567890123")
        await cache.manager.put(
            "player_data",
            "other-role-data",
            b"{}",
            tags=("player_data", "detail", identity, "role:102"),
            now=clock.value,
        )
        await cache.manager.put(
            "player_card",
            "other-role-card",
            b"other-card",
            tags=("player_card", "detail", identity, "role:102", "panel:102"),
            now=clock.value,
        )
        transport.overview = transport.overview.model_copy(
            update={"role_name": "刷新后的玩家"},
        )

        response = await service.refresh_role(_request(detail=True))

        assert isinstance(response, ImageResponse)
        assert transport.overview_calls == 2
        assert transport.role_detail_calls == 2
        assert renderer.detail_calls == 2
        assert "角色甲" in Image.open(response.image).info["dnaby.text"]
        assert (
            await cache.manager.get("player_data", "other-role-data", now=clock.value)
        ).status == "fresh"
        assert (
            await cache.manager.get("player_card", "other-role-card", now=clock.value)
        ).status == "fresh"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_refresh_send_card_false_refreshes_cache_without_returning_image(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    database, transport, renderer, _cache, service = await _service(tmp_path, clock)
    service.refresh_send_card = False
    try:
        response = await service.refresh_role(_request(detail=True))

        assert isinstance(response, PlainTextResponse)
        assert response.text == messages.PLAYER_CACHE_REFRESHED
        assert transport.overview_calls == 1
        assert transport.role_detail_calls == 1
        assert renderer.detail_calls == 1
        cached = await service.role_detail(_request(detail=True))
        assert isinstance(cached, ImageResponse)
        assert transport.role_detail_calls == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_admin_refresh_requires_admin_and_passes_explicit_uid() -> None:
    calls: list[tuple[object, str | None]] = []

    class Service:
        async def refresh_role(self, request, *, uid=None):
            calls.append((request, uid))
            return PlainTextResponse("刷新完成")

        async def clear_all_cache(self):
            return PlainTextResponse("清理完成")

    user_request = CommandRequest(
        command_id="refresh_role_card",
        text="kk刷新角色甲面板",
        parameters={"char_name": "角色甲"},
        actor=EventActor("user-1", "bot-1"),
        services={"player_service": Service()},
    )
    user_response = await player_refresh_role_use_case(
        user_request,
        CommandRegistry(()),
        **user_request.parameters,
    )

    assert isinstance(user_response, PlainTextResponse)
    assert calls[0][1] is None
    assert calls[0][0].parameters == {"char_name": "角色甲"}

    admin_request = CommandRequest(
        command_id="refresh_admin_role_card",
        text="kk刷新123456的角色甲面板",
        parameters={"uid": "123456", "char_name": "角色甲"},
        actor=EventActor("admin-1", "bot-1"),
        permission="admin",
        services={"player_service": Service()},
    )
    response = await player_refresh_admin_role_use_case(
        admin_request,
        CommandRegistry(()),
        **admin_request.parameters,
    )

    assert isinstance(response, PlainTextResponse)
    assert calls[1][1] == "123456"

    member_request = CommandRequest(
        command_id="refresh_admin_role_card",
        text="kk刷新123456的角色甲面板",
        parameters=admin_request.parameters,
        actor=admin_request.actor,
        permission="user",
        services=admin_request.services,
    )
    denied = await player_refresh_admin_role_use_case(
        member_request,
        CommandRegistry(()),
        **member_request.parameters,
    )
    assert isinstance(denied, PlainTextResponse)
    assert denied.text == messages.PLAYER_ADMIN_ONLY
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_clear_all_role_cache_command_only_clears_current_uid_player_entries(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    database, _transport, _renderer, cache, service = await _service(tmp_path, clock)
    try:
        identity = cache.identity_tag("user-1", "1234567890123")
        await cache.manager.put(
            "player_data",
            "player",
            b"{}",
            tags=("player_data", identity),
            now=clock.value,
        )
        await cache.manager.put(
            "player_card",
            "card",
            b"card",
            tags=("player_card", identity),
            now=clock.value,
        )
        await cache.manager.put("announcement", "keep", b"announcement", now=clock.value)
        request = CommandRequest(
            command_id="clear_player_cache",
            text="kk清理全部角色缓存",
            parameters={},
            actor=EventActor("user-1", "bot-1"),
            permission="user",
            services={"player_service": service},
        )

        response = await player_clear_all_cache_use_case(
            request,
            CommandRegistry(()),
        )

        assert isinstance(response, PlainTextResponse)
        assert response.text == messages.PLAYER_ALL_ROLE_CACHE_CLEARED
        assert (await cache.manager.get("player_data", "player", now=clock.value)).status == "miss"
        assert (await cache.manager.get("player_card", "card", now=clock.value)).status == "miss"
        assert (await cache.manager.get("announcement", "keep", now=clock.value)).status == "fresh"
    finally:
        await database.dispose()


def _old_file(path: Path, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"rendered")
    timestamp = now.timestamp() - 7200
    os.utime(path, (timestamp, timestamp))


def test_rendered_store_removes_expired_orphans_but_honors_active_leases(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    root = tmp_path / "rendered"
    store = RenderedFileStore(root, retention_seconds=3600)
    orphan = root / "player-orphan.png"
    active = root / "notices-active.png"
    unrelated = root / "panel_custom.png"
    _old_file(orphan, now)
    _old_file(active, now)
    _old_file(unrelated, now)
    store.register(active)

    report = store.cleanup(now=now)

    assert report.removed == 1
    assert report.skipped_active == 1
    assert not orphan.exists()
    assert active.exists()
    assert unrelated.exists()

    store.release(active)
    assert store.cleanup(now=now).removed == 1
    assert not active.exists()


def test_rendered_store_rejects_dotdot_escape_from_controlled_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rendered"
    root.mkdir()
    store = RenderedFileStore(root, retention_seconds=3600)

    with pytest.raises(ValueError, match="受控目录"):
        store.register(root / ".." / "outside.png")


@pytest.mark.asyncio
async def test_cache_maintenance_runs_cleanup_and_has_idempotent_lifecycle(
    tmp_path: Path,
) -> None:
    from src.infrastructure.cache import CacheManager

    manager = CacheManager(tmp_path / "cache")
    rendered = RenderedFileStore(tmp_path / "rendered", retention_seconds=3600)
    maintenance = CacheMaintenance(
        manager,
        rendered,
        interval_seconds=3600,
    )

    await maintenance.start()
    await maintenance.start()
    assert maintenance.started is True
    await maintenance.stop()
    await maintenance.stop()
    assert maintenance.started is False


def test_response_factory_registers_temporary_images_for_rendered_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rendered"
    root.mkdir()
    image = root / "player-sent.png"
    Image.new("RGBA", (2, 2), "red").save(image)
    store = RenderedFileStore(root, retention_seconds=1)
    tracked: list[str] = []

    class Event:
        def track_temporary_local_file(self, path: str) -> None:
            tracked.append(path)

        def image_result(self, value: object) -> object:
            return value

    response = ImageResponse(str(image), temporary=True)
    factory = ResponseFactory(temporary_roots=(root,), rendered_store=store)
    factory.build(Event(), response)

    assert tracked == [str(image)]
    now = datetime.now(timezone.utc)
    old_timestamp = now.timestamp() - 2
    os.utime(image, (old_timestamp, old_timestamp))

    report = store.cleanup(now=now)
    assert report.skipped_active == 1
    assert image.exists()

    store.release(image)
    assert store.cleanup(now=now).removed == 1
    assert not image.exists()
