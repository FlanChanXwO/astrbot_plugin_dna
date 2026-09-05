"""统一文件缓存核心的公开契约测试。"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

from src.infrastructure.cache import (
    CacheContentError,
    CacheManager,
    CacheMetadataError,
    CacheMissError,
)
from src.infrastructure.config import (
    CacheSettings,
    DnabySettings,
    generate_astrbot_schema,
)


def test_cache_settings_expose_the_planned_defaults() -> None:
    settings = DnabySettings.from_config({})

    assert settings.cache.ttl_hours == 24
    assert settings.cache.refresh_send_card is True

    schema = generate_astrbot_schema()
    cache_items = schema["cache"]["items"]
    assert set(cache_items) == {"ttl_hours", "refresh_send_card"}
    assert cache_items["ttl_hours"]["default"] == 24
    assert "-1" in cache_items["ttl_hours"]["hint"]
    assert "0" in cache_items["ttl_hours"]["hint"]
    assert cache_items["refresh_send_card"]["default"] is True


@pytest.mark.asyncio
async def test_negative_ttl_keeps_cache_until_explicit_invalidation(tmp_path) -> None:
    settings = DnabySettings.from_config(
        {"cache": {"ttl_hours": -1}},
    )
    manager = CacheManager(tmp_path, settings.cache)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    await manager.put("role", "permanent", b"card", now=created_at)

    lookup = await manager.get(
        "role",
        "permanent",
        now=created_at + timedelta(days=365),
    )
    assert lookup.status == "fresh"
    assert lookup.entry is not None
    assert await manager.cleanup(now=created_at + timedelta(days=365)) == 0

    assert await manager.invalidate("role", key="permanent") == 1
    invalidated = await manager.get(
        "role",
        "permanent",
        now=created_at + timedelta(days=365),
    )
    assert invalidated.status == "miss"
    assert invalidated.reason == "not_found"


@pytest.mark.asyncio
async def test_cache_manager_returns_fresh_entry_with_metadata(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    metadata = await manager.put(
        "role",
        "user-1:role-1",
        b"role-card",
        resource_version="resource-abc",
        tags=("role", "card"),
        now=created_at,
    )
    result = await manager.get(
        "role",
        "user-1:role-1",
        now=created_at + timedelta(minutes=29),
    )

    assert result.status == "fresh"
    assert result.entry is not None
    assert result.entry.content == b"role-card"
    assert result.entry.metadata.created_at == metadata.created_at
    assert result.entry.metadata.last_accessed_at == created_at + timedelta(minutes=29)
    assert metadata.cache_type == "role"
    assert metadata.key == manager.key_digest("user-1:role-1")
    assert len(metadata.content_sha256) == 64
    assert metadata.resource_version == "resource-abc"
    assert metadata.integrity == "complete"
    assert metadata.tags == ("role", "card")


def _require_decodable_image(content: bytes) -> bool:
    with Image.open(BytesIO(content)) as image:
        image.verify()
    return True


@pytest.mark.asyncio
async def test_invalid_content_never_replaces_a_complete_entry(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("role", "user-1:role-1", b"complete", now=created_at)

    with pytest.raises(CacheContentError):
        await manager.put(
            "role",
            "user-1:role-1",
            b"not-an-image",
            validator=_require_decodable_image,
            now=created_at + timedelta(minutes=1),
        )
    with pytest.raises(CacheContentError):
        await manager.put("role", "empty", b"", now=created_at)

    result = await manager.get("role", "user-1:role-1", now=created_at)
    missing = await manager.get("role", "empty", now=created_at)

    assert result.status == "fresh"
    assert result.entry is not None
    assert result.entry.content == b"complete"
    assert missing.status == "miss"
    assert missing.reason == "not_found"


@pytest.mark.asyncio
async def test_read_validator_rejects_undecodable_payload(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("image", "avatar", b"not-an-image", now=created_at)

    result = await manager.get(
        "image",
        "avatar",
        validator=_require_decodable_image,
        now=created_at,
    )

    assert result.status == "miss"
    assert result.entry is None
    assert result.reason == "invalid_content"


@pytest.mark.asyncio
async def test_incomplete_integrity_never_returns_a_successful_lookup(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("image", "partial", b"partial", now=created_at)
    sidecar = next(tmp_path.rglob("*.meta.json"))
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["integrity"] = "incomplete"
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")

    result = await manager.get("image", "partial", now=created_at)

    assert result.status == "miss"
    assert result.entry is None
    assert result.reason == "invalid_integrity"


@pytest.mark.asyncio
async def test_metadata_identity_must_match_the_requested_cache_entry(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("role", "user-a", b"card", now=created_at)
    sidecar = next(tmp_path.rglob("*.meta.json"))
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["key"] = manager.key_digest("user-b")
    metadata["cache_type"] = "profile"
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")

    result = await manager.get("role", "user-a", now=created_at)

    assert result.status == "miss"
    assert result.entry is None
    assert result.reason == "invalid_metadata"


@pytest.mark.asyncio
async def test_put_does_not_silently_overwrite_corrupt_metadata(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    await manager.put("role", "user-a", b"card")
    sidecar = next(tmp_path.rglob("*.meta.json"))
    sidecar.write_text("{not-json", encoding="utf-8")

    with pytest.raises(CacheMetadataError):
        await manager.put("role", "user-a", b"new-card")


@pytest.mark.asyncio
async def test_cleanup_removes_entries_past_the_hard_retention_window(tmp_path) -> None:
    settings = CacheSettings(ttl_hours=1)
    manager = CacheManager(tmp_path, settings)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("role", "expired", b"old", now=created_at)

    removed = await manager.cleanup(now=created_at + timedelta(hours=1))
    result = await manager.get(
        "role",
        "expired",
        now=created_at + timedelta(hours=1),
    )

    assert removed == 1
    assert result.status == "miss"
    assert result.reason == "not_found"
    assert not list(tmp_path.rglob("*.data"))
    assert not list(tmp_path.rglob("*.meta.json"))


@pytest.mark.asyncio
async def test_cache_manager_returns_miss_at_unified_ttl_boundary(tmp_path) -> None:
    settings = CacheSettings(ttl_hours=1)
    manager = CacheManager(tmp_path, settings)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("role", "aging", b"card", now=created_at)

    fresh = await manager.get(
        "role",
        "aging",
        now=created_at + timedelta(minutes=59),
    )
    expired = await manager.get(
        "role",
        "aging",
        now=created_at + timedelta(hours=1),
    )

    assert fresh.status == "fresh"
    assert fresh.entry is not None
    assert fresh.entry.content == b"card"
    assert expired.status == "miss"
    assert expired.entry is None
    assert expired.reason == "ttl_expired"


@pytest.mark.asyncio
async def test_sidecar_metadata_is_persisted_without_the_raw_cache_key(tmp_path) -> None:
    manager = CacheManager(tmp_path)

    await manager.put(
        "profile",
        "token=secret-value",
        b"payload",
        resource_version="resource-1",
        tags=("profile", "profile", "user"),
    )

    sidecars = list(tmp_path.rglob("*.meta.json"))
    assert len(sidecars) == 1
    raw = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert raw["cache_type"] == "profile"
    assert raw["key"] == manager.key_digest("token=secret-value")
    assert raw["content_sha256"] == (
        "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"
    )
    assert raw["resource_version"] == "resource-1"
    assert raw["integrity"] == "complete"
    assert raw["tags"] == ["profile", "user"]
    assert raw["lease_count"] == 0
    assert "secret-value" not in sidecars[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_active_lease_protects_an_expired_entry_from_cleanup(tmp_path) -> None:
    settings = CacheSettings(ttl_hours=1)
    manager = CacheManager(tmp_path, settings)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    expiry = created_at + timedelta(hours=1)
    await manager.put("role", "leased", b"card", now=created_at)

    async with manager.lease("role", "leased", now=created_at) as entry:
        assert entry.content == b"card"
        current = await manager.get("role", "leased", now=created_at)
        assert current.entry is not None
        assert current.entry.metadata.lease_count == 1
        assert await manager.cleanup(now=expiry) == 0
        assert (await manager.get("role", "leased", now=expiry)).status == "miss"

    assert await manager.cleanup(now=expiry) == 1
    assert (await manager.get("role", "leased", now=expiry)).status == "miss"


@pytest.mark.asyncio
async def test_lease_validator_rejects_undecodable_payload(tmp_path) -> None:
    manager = CacheManager(tmp_path)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await manager.put("image", "leased", b"not-an-image", now=created_at)

    with pytest.raises(CacheMissError):
        async with manager.lease(
            "image",
            "leased",
            validator=_require_decodable_image,
            now=created_at,
        ):
            raise AssertionError("不可解码内容不应进入租约上下文")


@pytest.mark.asyncio
async def test_concurrent_leases_keep_the_entry_until_all_consumers_release(
    tmp_path,
) -> None:
    settings = CacheSettings(ttl_hours=1)
    manager = CacheManager(tmp_path, settings)
    created_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    expiry = created_at + timedelta(hours=1)
    await manager.put("role", "shared", b"card", now=created_at)
    first_ready = asyncio.Event()
    second_ready = asyncio.Event()
    release = asyncio.Event()

    async def hold(ready: asyncio.Event) -> None:
        async with manager.lease("role", "shared", now=created_at) as entry:
            assert entry.content == b"card"
            ready.set()
            await release.wait()

    first = asyncio.create_task(hold(first_ready))
    await first_ready.wait()
    second = asyncio.create_task(hold(second_ready))
    await second_ready.wait()

    current = await manager.get("role", "shared", now=created_at)
    assert current.entry is not None
    assert current.entry.metadata.lease_count == 2
    assert await manager.cleanup(now=expiry) == 0

    release.set()
    await asyncio.gather(first, second)
    assert await manager.cleanup(now=expiry) == 1
