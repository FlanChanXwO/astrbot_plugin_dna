"""运行期素材解析的 L1/L2/网络优先级契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.resources import ResourceGenerationError
from src.infrastructure.resources import generation as generation_module
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


def test_generation_image_decompression_bomb_is_resource_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pillow 解压炸弹必须落入 generation 的统一资源异常边界。"""

    path = tmp_path / "candidate.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)

    def raise_bomb(*_args: object, **_kwargs: object) -> None:
        raise Image.DecompressionBombError("too large")

    monkeypatch.setattr(generation_module.Image, "open", raise_bomb)

    with pytest.raises(ResourceGenerationError, match="资源候选图片不可解码"):
        generation_module._validate_image_decodability(path)


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
async def test_bind_renderer_shares_generation_lease_with_asset_resolver(
    tmp_path: Path,
) -> None:
    """renderer 资源视图和图片 resolver 必须固定到同一个 generation lease。"""

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
    commit_sha = "b" * 40
    coordinator._current = ResourceSnapshot(
        commit_sha=commit_sha,
        root=public,
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("images",),
            resource_version="test",
        ),
        player_resources=ResourceMap.from_root(public),
        encyclopedia_resources=EncyclopediaResourceStore(),
    )
    base_resolver = AssetResolver(
        dynamic_root=tmp_path / "cache" / "assets",
        coordinator=coordinator,
    )
    renderer = SimpleNamespace(resources=None, asset_resolver=base_resolver)

    with coordinator.bind_renderer(
        renderer,
        "player_resources",
        asset_resolver_attr="asset_resolver",
    ) as bound:
        assert bound.resources is coordinator._current.player_resources
        assert bound.asset_resolver.coordinator is None
        assert bound.asset_resolver.snapshot_root == public
        assert coordinator._leases == {commit_sha: 1}
        resolved = await bound.asset_resolver.resolve("role_avatar", 101)
        assert resolved.path == public_path

    assert coordinator._leases == {}
