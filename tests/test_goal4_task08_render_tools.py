"""Goal 4 / Task 08：缓存、离线工具与 artifact 清理契约。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from scripts import compare_renders, regenerate_astrbot_images
from src.infrastructure.rendering.artifact import RenderedArtifact
from src.infrastructure.rendering.artifact_store import (
    read_rendered_artifact,
    write_rendered_artifact,
)
from src.infrastructure.rendering.temporary import RenderedFileStore


def _jpeg_bytes(size: tuple[int, int] = (31, 19)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "#4e6f91").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _png_bytes(size: tuple[int, int] = (31, 19)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "#4e6f91").save(buffer, format="PNG")
    return buffer.getvalue()


def _published_jpeg(root: Path):
    artifact = RenderedArtifact.from_bytes(
        _jpeg_bytes(),
        media_type="image/jpeg",
        metadata={
            "dnaby.text": "二重螺旋 · 密函\n角色:\n1. 扼守",
            "dnaby.layout": {
                "width": 31,
                "height": 19,
                "sections": [{"name": "角色", "items": 1}],
            },
            "dnaby.resources": [{"kind": "font", "status": "provided"}],
        },
    )
    return write_rendered_artifact(root, artifact, prefix="notices-")


def test_compare_report_reads_metadata_from_jpeg_sidecar(tmp_path: Path) -> None:
    response = _published_jpeg(tmp_path / "rendered")
    legacy = Image.new("RGB", (31, 19), "#4e6f91")
    rewrite = Image.open(response.image).convert("RGB")

    report = compare_renders._report(
        legacy,
        rewrite,
        Path(response.image),
        tmp_path / "report.md",
    )

    assert "二重螺旋 · 密函" in report
    assert '"name": "角色"' in report
    assert '"kind": "font"' in report


@pytest.mark.parametrize(
    ("payload", "media_type", "suffix"),
    [
        (_jpeg_bytes(), "image/jpeg", ".jpg"),
        (_png_bytes(), "image/png", ".png"),
    ],
)
def test_regenerate_exports_real_format_with_valid_pair(
    tmp_path: Path,
    payload: bytes,
    media_type: str,
    suffix: str,
) -> None:
    artifact = RenderedArtifact.from_bytes(
        payload,
        media_type=media_type,  # type: ignore[arg-type]
    )
    response = write_rendered_artifact(
        tmp_path / "rendered",
        artifact,
        prefix="notices-",
    )
    stale_suffix = ".png" if suffix == ".jpg" else ".jpg"
    stale_image = (tmp_path / "output" / "weekly_report_current").with_suffix(
        stale_suffix
    )
    stale_image.parent.mkdir(parents=True)
    stale_image.write_bytes(b"stale")
    stale_image.with_name(stale_image.name + ".json").write_text("{}", encoding="utf-8")

    exported = regenerate_astrbot_images._export_rendered(
        Path(response.image),
        tmp_path / "output" / "weekly_report_current",
    )

    assert exported.suffix == suffix
    assert exported.name == f"weekly_report_current{suffix}"
    assert not stale_image.exists()
    assert not stale_image.with_name(stale_image.name + ".json").exists()
    assert read_rendered_artifact(exported).data == payload


def test_rendered_cleanup_removes_old_jpeg_pair_and_manifest_orphan(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    response = _published_jpeg(tmp_path / "rendered")
    image = Path(response.image)
    sidecar = Path(response.sidecar)
    manifest = Path(response.manifest)
    timestamp = now.timestamp() - 7200
    for path in (image, sidecar, manifest):
        os.utime(path, (timestamp, timestamp))

    orphan_manifest = image.with_name("notices-orphan.jpg.manifest.json")
    orphan_manifest.write_text("{}", encoding="utf-8")
    os.utime(orphan_manifest, (timestamp, timestamp))

    report = RenderedFileStore(
        tmp_path / "rendered",
        retention_seconds=3600,
    ).cleanup(now=now)

    assert report.removed == 2
    assert not image.exists()
    assert not sidecar.exists()
    assert not manifest.exists()
    assert not orphan_manifest.exists()


@pytest.mark.asyncio
async def test_announcement_cache_metadata_records_real_media_type(
    tmp_path: Path,
) -> None:
    from src.infrastructure.cache import CacheManager
    from src.infrastructure.rendering.notices import NoticesRenderer
    from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore

    manager = CacheManager(tmp_path / "cache")
    renderer = NoticesRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        cache_manager=manager,
    )

    await renderer._store_image(
        "announcement-key",
        _jpeg_bytes(),
        tags=("announcement", "detail"),
    )
    lookup = await manager.get("announcement", "announcement-key")

    assert lookup.entry is not None
    assert "media:image/jpeg" in lookup.entry.metadata.tags


@pytest.mark.asyncio
async def test_legacy_announcement_manifest_misses_and_rebuilds_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from src.infrastructure.cache import CacheManager
    from src.infrastructure.rendering import notices as notices_module
    from src.infrastructure.rendering.notices import NoticesRenderer
    from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
    from src.modules.notices.contracts import AnnBlock, AnnDetail

    manager = CacheManager(tmp_path / "cache")
    renderer = NoticesRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        cache_manager=manager,
    )
    detail = AnnDetail(
        post_id="7",
        title="格式迁移公告",
        blocks=(AnnBlock(kind="text", text="正文"),),
    )
    await renderer._store_image(
        renderer.detail_cache_key(detail, page_index=0),
        _jpeg_bytes(),
        tags=("announcement", "detail"),
    )
    await manager.put(
        "announcement",
        renderer.detail_manifest_key(detail),
        b'{"pages":[0]}',
    )
    calls = 0
    rebuilt = _jpeg_bytes((41, 23))

    async def render_detail(*_: object, **__: object) -> bytes:
        nonlocal calls
        calls += 1
        return rebuilt

    monkeypatch.setattr(notices_module, "draw_ann_detail_card", render_detail)

    rendered = await renderer.render_ann_detail(detail)

    assert calls == 1
    assert rendered.path.read_bytes() == rebuilt
    manifest = await manager.get(
        "announcement",
        renderer.detail_manifest_key(detail),
    )
    assert manifest.entry is not None
    assert json.loads(manifest.entry.content)["schema_version"] == 2
