"""Goal 4 / Task 07：公告与密函 T2I 输出及超长分页契约。"""

from __future__ import annotations
from io import BytesIO
from pathlib import Path
from PIL import Image
from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.infrastructure.rendering.notices import NoticesRenderer
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.modules.notices.service import NoticesService


def _jpeg_bytes(size: tuple[int, int] = (29, 17)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "#7d4ca5").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def test_notices_writer_preserves_normal_t2i_bytes(tmp_path: Path) -> None:
    renderer = NoticesRenderer(
        tmp_path / "rendered", EncyclopediaResourceStore(tmp_path / "resources")
    )
    payload = _jpeg_bytes()
    rendered = renderer._write_cached(
        payload,
        lines=["公告详情", "正文"],
        resources=[],
        sections=[{"name": "详情正文", "items": 1}],
    )
    assert rendered.path.suffix == ".jpg"
    assert rendered.path.read_bytes() == payload
    artifact = read_rendered_artifact(rendered.path)
    assert artifact.metadata["dnaby.text"] == "公告详情\n正文"


def test_notices_response_propagates_artifact_pair(tmp_path: Path) -> None:
    renderer = NoticesRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore(tmp_path / "resources"),
    )
    rendered = renderer._write_cached(
        _jpeg_bytes(),
        lines=["密函"],
        resources=[],
        sections=[],
    )

    response = NoticesService._image_response(rendered)

    assert response.sidecar == rendered.sidecar
    assert response.manifest == rendered.manifest
