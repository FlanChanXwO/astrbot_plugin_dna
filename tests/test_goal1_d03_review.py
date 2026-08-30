"""D03 对 O07/O08 的并发、故障和路径边界审查契约。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from src.infrastructure.cache import CacheManager, CacheMetadataError, CacheMissError
from src.infrastructure.resources import (
    ResourceGenerationError,
    ResourceSnapshotCoordinator,
    ResourceSyncError,
    ResourceSyncResult,
)
from src.modules.operations import resource_service as resource_service_module
from src.modules.operations.resource_service import ResourceUpdateService
from src.utils import image as legacy_image
from src.utils import image_utils
from src.utils.image_utils import ImageFetchError


@pytest.mark.asyncio
@pytest.mark.parametrize("linked_entry", ["data", "metadata"])
async def test_cache_read_and_lease_do_not_follow_entry_symlinks(
    tmp_path: Path,
    linked_entry: str,
):
    manager = CacheManager(tmp_path / "cache")
    await manager.put("role", "user-1", b"payload")
    data_path, metadata_path = manager._paths("role", "user-1")

    external = tmp_path / f"external-{linked_entry}"
    source = data_path if linked_entry == "data" else metadata_path
    external.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(external)

    result = await manager.get("role", "user-1")

    assert result.status == "miss"
    assert result.reason == "unsafe_path"
    with pytest.raises(CacheMissError, match="路径不安全"):
        async with manager.lease("role", "user-1"):
            raise AssertionError("符号链接不应进入缓存租约")


@pytest.mark.asyncio
async def test_cache_put_does_not_write_through_cache_directory_symlink(tmp_path: Path):
    root = tmp_path / "cache"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "role").symlink_to(outside, target_is_directory=True)
    manager = CacheManager(root)

    with pytest.raises(CacheMetadataError, match="缓存目录路径不安全"):
        await manager.put("role", "user-1", b"payload")

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_cancelled_sync_waiter_keeps_worker_failure_observable(
    monkeypatch: pytest.MonkeyPatch,
):
    started = Event()
    release = Event()

    def synchronize() -> ResourceSyncResult:
        started.set()
        release.wait()
        raise ResourceSyncError("worker failed")

    messages: list[str] = []
    monkeypatch.setattr(resource_service_module.logger, "warning", messages.append)
    service = ResourceUpdateService(synchronize=synchronize)
    waiter = asyncio.create_task(service.synchronize_once())
    await asyncio.to_thread(started.wait)
    worker = service._inflight
    assert worker is not None

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    while not worker.done():
        await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert any("共享资源同步任务失败" in message for message in messages)
    assert worker.exception() is not None


@pytest.mark.asyncio
async def test_image_download_rejects_symlinked_cache_directory(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ImageFetchError, match="符号链接"):
        await image_utils.download(
            "https://cdn.example.test/avatar.png",
            cache_dir,
            "avatar.png",
        )

    assert not (outside / "avatar.png").exists()


@pytest.mark.asyncio
async def test_optional_cached_image_does_not_follow_symlink_without_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    outside = tmp_path / "outside.png"
    buffer = BytesIO()
    Image.new("RGBA", (2, 2), "red").save(buffer, format="PNG")
    outside.write_bytes(buffer.getvalue())
    (cache_dir / "avatar_42.png").symlink_to(outside)
    monkeypatch.setattr(legacy_image, "AVATAR_PATH", cache_dir)

    image = await legacy_image.get_avatar_img(42)

    assert image.size == (256, 256)


def test_resource_snapshot_rejects_symlinked_generation_root(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    generations_root = tmp_path / "resource_generations"
    generations_root.symlink_to(outside, target_is_directory=True)
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=generations_root,
    )

    with pytest.raises(ResourceGenerationError, match="generation 根目录.*符号链接"):
        coordinator.initialize()
