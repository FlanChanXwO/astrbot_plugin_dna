"""运行期素材解析的 L1/L2/网络优先级契约。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.infrastructure.resources.resolver import AssetResolver


class _RecordingDownloader:
    """把下载调用记录下来，并写入一张可解码的图片。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    async def fetch(self, url: str, target: Path, *, tag: str = "") -> Path:
        del tag
        self.calls.append((url, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (32, 32), "green").save(target)
        return target


def _write_image(path: Path, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), color).save(path)


@pytest.mark.asyncio
async def test_l1_hit_skips_l2_and_network(tmp_path: Path) -> None:
    """公共 generation 命中时直接返回，不复制到动态缓存，也不联网。"""

    public = tmp_path / "generation"
    public_path = public / "images" / "role_avatar" / "101.png"
    _write_image(public_path)
    downloader = _RecordingDownloader()
    resolver = AssetResolver(
        snapshot_root=public,
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    resolved = await resolver.resolve(
        "role_avatar", 101, url="https://example.test/101.png"
    )

    assert resolved.path == public_path
    assert resolved.source == "verified_snapshot"
    assert resolved.status == "provided"
    assert not (tmp_path / "cache" / "assets").exists()
    assert downloader.calls == []


@pytest.mark.asyncio
async def test_l1_miss_uses_valid_l2_without_network(tmp_path: Path) -> None:
    """公共 generation 缺失时使用有效动态缓存，不触发下载。"""

    dynamic_path = tmp_path / "cache" / "assets" / "game_avatar" / "avatar_101.png"
    _write_image(dynamic_path, "blue")
    downloader = _RecordingDownloader()
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    resolved = await resolver.resolve(
        "role_avatar", 101, url="https://example.test/101.png"
    )

    assert resolved.path == dynamic_path
    assert resolved.source == "dynamic_cache"
    assert resolved.status == "provided"
    assert downloader.calls == []


@pytest.mark.asyncio
async def test_double_miss_downloads_only_to_l2(tmp_path: Path) -> None:
    """L1/L2 均缺失时才下载，并把结果写入动态缓存。"""

    downloader = _RecordingDownloader()
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    resolved = await resolver.resolve(
        "weapon",
        202,
        url="https://example.test/weapon-202.png",
    )

    expected = tmp_path / "cache" / "assets" / "weapon" / "weapon_202.png"
    assert resolved.path == expected
    assert resolved.source == "download"
    assert resolved.status == "provided"
    assert expected.is_file()
    assert downloader.calls == [("https://example.test/weapon-202.png", expected)]
    assert not (tmp_path / "generation").exists()


@pytest.mark.asyncio
async def test_corrupt_l1_is_not_overwritten_and_valid_l2_wins(tmp_path: Path) -> None:
    """损坏的 L1 只被跳过，不能被下载结果覆盖。"""

    public_path = tmp_path / "generation" / "images" / "role_paint" / "303.png"
    public_path.parent.mkdir(parents=True, exist_ok=True)
    original = b"not-an-image"
    public_path.write_bytes(original)
    dynamic_path = tmp_path / "cache" / "assets" / "paint" / "paint_303.png"
    _write_image(dynamic_path, "purple")
    downloader = _RecordingDownloader()
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    resolved = await resolver.resolve(
        "role_paint",
        303,
        url="https://example.test/paint-303.png",
    )

    assert resolved.path == dynamic_path
    assert resolved.source == "dynamic_cache"
    assert downloader.calls == []
    assert public_path.read_bytes() == original


@pytest.mark.asyncio
async def test_coordinator_binds_resolver_to_current_generation(tmp_path: Path) -> None:
    """解析器通过 coordinator context 固定当前 generation。"""

    from src.infrastructure.rendering import ResourceMap
    from src.infrastructure.resources import (
        EncyclopediaResourceStore,
        ResourceManifest,
        ResourceSnapshot,
        ResourceSnapshotCoordinator,
    )

    public = tmp_path / "generation"
    public_path = public / "images" / "role_avatar" / "101.png"
    _write_image(public_path)
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "repository",
        generations_root=tmp_path / "generations",
    )
    coordinator._current = ResourceSnapshot(  # noqa: SLF001 - 构造已验证快照夹具
        commit_sha="a" * 40,
        root=public,
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("images",),
            resource_version="test",
        ),
        player_resources=ResourceMap.from_root(public),
        encyclopedia_resources=EncyclopediaResourceStore(),
    )

    with coordinator.bind_asset_resolver(
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=_RecordingDownloader(),
    ) as resolver:
        resolved = await resolver.resolve("role_avatar", 101)
        assert resolved.path == public_path
        assert resolved.source == "verified_snapshot"

    assert coordinator._leases == {}  # noqa: SLF001 - lease 必须在 context 退出时释放
