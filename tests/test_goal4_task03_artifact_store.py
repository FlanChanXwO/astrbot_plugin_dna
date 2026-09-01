"""Goal 4 / Task 03：artifact、sidecar、缓存和响应边界契约。"""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.entry.response import ImageResponse, ResponseFactory
from src.infrastructure.rendering.artifact import RenderedArtifact
from src.infrastructure.rendering.artifact_store import (
    read_rendered_artifact,
    write_rendered_artifact,
)
from src.infrastructure.rendering.temporary import RenderedFileStore


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (13, 17), "#123456").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


class CleanupEvent:
    def __init__(self) -> None:
        self.tracked: list[str] = []

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(path)

    def image_result(self, image: object) -> object:
        return image


def test_write_and_read_artifact_preserve_bytes_and_sidecar(tmp_path: Path) -> None:
    payload = _jpeg_bytes()
    artifact = RenderedArtifact.from_bytes(
        payload,
        media_type="image/jpeg",
        metadata={"dnaby.text": "原始 bytes"},
    )

    response = write_rendered_artifact(tmp_path / "rendered", artifact, prefix="player-")

    assert isinstance(response, ImageResponse)
    image_path = Path(response.image)
    sidecar_path = Path(response.sidecar)
    assert image_path.read_bytes() == payload
    assert image_path.suffix == ".jpg"
    assert sidecar_path == image_path.with_name(image_path.name + ".json")
    raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert raw["sha256"] == artifact.sha256
    assert raw["media_type"] == "image/jpeg"
    assert raw["metadata"] == {"dnaby.text": "原始 bytes"}

    restored = read_rendered_artifact(image_path)
    assert restored.data == payload
    assert restored.sha256 == artifact.sha256
    assert restored.metadata["dnaby.text"] == "原始 bytes"


def test_response_factory_tracks_image_and_sidecar_as_a_pair(tmp_path: Path) -> None:
    artifact = RenderedArtifact.from_bytes(_jpeg_bytes(), media_type="image/jpeg")
    response = write_rendered_artifact(tmp_path / "rendered", artifact, prefix="notices-")
    event = CleanupEvent()

    ResponseFactory(temporary_roots=(tmp_path / "rendered",)).build(event, response)

    assert event.tracked == [str(response.image), str(response.sidecar)]


def test_read_artifact_rejects_sidecar_hash_mismatch(tmp_path: Path) -> None:
    artifact = RenderedArtifact.from_bytes(_jpeg_bytes(), media_type="image/jpeg")
    response = write_rendered_artifact(tmp_path / "rendered", artifact, prefix="player-")
    sidecar_path = Path(response.sidecar)
    raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    raw["sha256"] = "0" * 64
    sidecar_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA256"):
        read_rendered_artifact(Path(response.image))


def test_rendered_cleanup_removes_orphaned_sidecar_with_image(tmp_path: Path) -> None:
    artifact = RenderedArtifact.from_bytes(_jpeg_bytes(), media_type="image/jpeg")
    response = write_rendered_artifact(tmp_path / "rendered", artifact, prefix="player-")
    image_path = Path(response.image)
    sidecar_path = Path(response.sidecar)
    old = image_path.stat().st_mtime - 1000
    os.utime(image_path, (old, old))
    os.utime(sidecar_path, (old, old))
    store = RenderedFileStore(tmp_path / "rendered", retention_seconds=60)

    report = store.cleanup()

    assert report.removed == 1
    assert not image_path.exists()
    assert not sidecar_path.exists()

@pytest.mark.asyncio
async def test_cache_manager_can_validate_jpeg_and_png_without_reencoding(tmp_path: Path) -> None:
    from src.infrastructure.cache import CacheManager
    from src.infrastructure.rendering.artifact_store import artifact_validator

    manager = CacheManager(tmp_path / "cache")
    payload = _jpeg_bytes()
    await manager.put(
        "player",
        "user/uid",
        payload,
        validator=artifact_validator("image/jpeg"),
    )

    lookup = await manager.get(
        "player",
        "user/uid",
        validator=artifact_validator("image/jpeg"),
    )

    assert lookup.status == "fresh"
    assert lookup.entry is not None
    assert lookup.entry.content == payload
