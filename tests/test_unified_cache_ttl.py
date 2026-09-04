"""统一内容缓存 TTL 的新契约测试。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.infrastructure.cache import CacheManager, CacheMissError
from src.infrastructure.config import (
    CacheSettings,
    DnabySettings,
    generate_astrbot_schema,
)
from src.infrastructure.persistence import AsyncDatabase
from src.modules.player import messages
from tests.test_goal1_o10_player_cache import _request, _service

UTC_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_cache_ttl_and_refresh_send_card_defaults_and_supported_bounds() -> None:
    assert CacheSettings().ttl_hours == 24
    assert CacheSettings().refresh_send_card is True
    assert set(CacheSettings.model_fields) == {"ttl_hours", "refresh_send_card"}

    for value in (-1, 0, 1, 24):
        assert CacheSettings(ttl_hours=value).ttl_hours == value

    assert CacheSettings(refresh_send_card=True).refresh_send_card is True
    assert CacheSettings(refresh_send_card=False).refresh_send_card is False

    with pytest.raises(ValidationError):
        CacheSettings(ttl_hours=-2)


def test_legacy_cache_fields_are_discarded_but_refresh_send_card_is_preserved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = {
        "cache": {
            "fresh_ttl_minutes": 5,
            "retention_ttl_hours": 2,
            "announcement_ttl_hours": 3,
            "refresh_send_card": False,
        },
    }
    caplog.set_level("WARNING")

    settings = DnabySettings.from_config(config)

    assert settings.cache.ttl_hours == 24
    assert settings.cache.refresh_send_card is False
    assert not set(config["cache"]) & {
        "fresh_ttl_minutes",
        "retention_ttl_hours",
        "announcement_ttl_hours",
    }
    assert config["cache"]["refresh_send_card"] is False
    assert "丢弃已移除的缓存配置" in caplog.text
    for field in (
        "fresh_ttl_minutes",
        "retention_ttl_hours",
        "announcement_ttl_hours",
    ):
        assert field in caplog.text
    assert "cache.refresh_send_card" not in caplog.text


def test_cache_schema_exposes_ttl_and_refresh_send_card() -> None:
    cache_items = generate_astrbot_schema()["cache"]["items"]

    assert set(cache_items) == {"ttl_hours", "refresh_send_card"}
    assert cache_items["ttl_hours"]["default"] == 24
    assert "-1" in cache_items["ttl_hours"]["hint"]
    assert "0" in cache_items["ttl_hours"]["hint"]
    assert cache_items["refresh_send_card"]["default"] is True
    assert "图片" in cache_items["refresh_send_card"]["hint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_type", ["player_data", "player_card", "announcement", "mh"])
async def test_positive_ttl_expiration_is_a_miss_for_every_cache_type(
    tmp_path: Path,
    cache_type: str,
) -> None:
    manager = CacheManager(tmp_path, CacheSettings(ttl_hours=1))
    await manager.put(cache_type, "same-key", b"payload", now=UTC_NOW)

    fresh = await manager.get(cache_type, "same-key", now=UTC_NOW + timedelta(minutes=59))
    expired = await manager.get(cache_type, "same-key", now=UTC_NOW + timedelta(hours=1))

    assert fresh.status == "fresh"
    assert fresh.entry is not None
    assert expired.status == "miss"
    assert expired.entry is None
    assert expired.reason == "ttl_expired"


@pytest.mark.asyncio
async def test_zero_ttl_validates_put_but_never_reads_or_writes_disk(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path / "cache", CacheSettings(ttl_hours=0))

    metadata = await manager.put("player_data", "memory-only", b"payload")

    assert metadata.content_sha256 == hashlib.sha256(b"payload").hexdigest()
    assert not manager.root.exists()
    lookup = await manager.get("player_data", "memory-only", now=UTC_NOW)
    assert lookup.status == "miss"
    assert lookup.entry is None
    assert lookup.reason == "disabled"
    with pytest.raises(CacheMissError, match="禁用"):
        async with manager.lease("player_data", "memory-only", now=UTC_NOW):
            raise AssertionError("disabled cache must never lease")


@pytest.mark.asyncio
async def test_zero_ttl_cleanup_removes_existing_unleased_entries_but_keeps_active_lease(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    seeded = CacheManager(root, CacheSettings(ttl_hours=1))
    disabled = CacheManager(root, CacheSettings(ttl_hours=0))
    await seeded.put("announcement", "old", b"payload", now=UTC_NOW)

    async with seeded.lease("announcement", "old", now=UTC_NOW):
        assert await disabled.cleanup(now=UTC_NOW) == 0
        assert list(root.rglob("*.data"))
        assert list(root.rglob("*.meta.json"))

    assert await disabled.cleanup(now=UTC_NOW) == 1
    assert not list(root.rglob("*.data"))
    assert not list(root.rglob("*.meta.json"))


@pytest.mark.asyncio
async def test_negative_ttl_is_permanent_for_get_cleanup_and_invalidate(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path, CacheSettings(ttl_hours=-1))
    await manager.put("mh", "permanent", b"payload", now=UTC_NOW)

    lookup = await manager.get("mh", "permanent", now=UTC_NOW + timedelta(days=365))
    assert lookup.status == "fresh"
    assert lookup.entry is not None
    assert await manager.cleanup(now=UTC_NOW + timedelta(days=365)) == 0

    assert await manager.invalidate("mh", key="permanent") == 1
    assert (await manager.get("mh", "permanent", now=UTC_NOW)).reason == "not_found"


def test_runtime_keeps_rendered_cleanup_independent_from_content_ttl(tmp_path: Path) -> None:
    from src.bootstrap import build_runtime

    for ttl_hours, expected_interval in ((0, 24 * 60 * 60), (-1, 24 * 60 * 60), (2, 2 * 60 * 60)):
        runtime = build_runtime(
            SimpleNamespace(register_web_api=lambda *args: None),
            {"cache": {"ttl_hours": ttl_hours}},
            database=AsyncDatabase(tmp_path / f"db-{ttl_hours}.sqlite3"),
        )
        maintenance = runtime.services["cache_maintenance"]
        rendered = runtime.services["rendered_store"]
        assert maintenance.interval_seconds == expected_interval
        assert rendered.retention_seconds == 24 * 60 * 60


@pytest.mark.asyncio
async def test_player_cache_disabled_fetches_and_renders_every_time(tmp_path: Path) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock

    clock = MutableClock()
    database, transport, renderer, cache, service = await _service(tmp_path, clock)
    cache.manager.settings = CacheSettings(ttl_hours=0)
    try:
        first = await service.role_overview(_request())
        second = await service.role_overview(_request())

        assert isinstance(first, ImageResponse)
        assert isinstance(second, ImageResponse)
        assert transport.overview_calls == 2
        assert renderer.overview_calls == 2
        assert not list((tmp_path / "cache").rglob("*.data"))
        assert service.refresh_send_card is True
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_manual_role_refresh_returns_notice_and_a_new_card(tmp_path: Path) -> None:
    from tests.test_goal1_o10_player_cache import MutableClock

    clock = MutableClock()
    database, _transport, _renderer, _cache, service = await _service(tmp_path, clock)
    try:
        response = await service.refresh_role(_request(detail=True))
        assert isinstance(response, ChainResponse)
        assert isinstance(response.components[0], PlainTextResponse)
        assert isinstance(response.components[1], ImageResponse)
        assert response.components[0].text == messages.PLAYER_ROLE_REFRESHED.format(name="角色甲")
        assert response.components[1].incomplete is False
    finally:
        await database.dispose()
