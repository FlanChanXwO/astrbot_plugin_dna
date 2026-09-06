"""Goal 4 / Task 05：百科域 T2I 原始图片直出契约。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.infrastructure.rendering.encyclopedia import EncyclopediaRenderer
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore


def _jpeg_bytes(*, size: tuple[int, int] = (37, 19)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "#7457a8").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def test_encyclopedia_writer_publishes_original_t2i_jpeg_and_sidecar(
    tmp_path: Path,
) -> None:
    payload = _jpeg_bytes()
    renderer = EncyclopediaRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore(tmp_path / "resources"),
    )

    rendered = renderer._write(
        payload,
        lines=["资料玩家", "UID ***"],
        resources=[
            {"kind": "font", "key": "dna_fonts", "status": "placeholder", "source": ""}
        ],
        sections=[{"name": "便笺", "items": 4}],
    )

    assert rendered.path.suffix == ".jpg"
    assert rendered.path.read_bytes() == payload
    assert rendered.media_type == "image/jpeg"
    assert rendered.width == 37
    assert rendered.height == 19
    assert rendered.sidecar is not None and rendered.sidecar.is_file()
    assert rendered.manifest is not None and rendered.manifest.is_file()

    artifact = read_rendered_artifact(rendered.path)
    assert artifact.data == payload
    assert artifact.metadata["dnaby.text"] == "资料玩家\nUID ***"
    assert artifact.metadata["dnaby.layout"] == {
        "width": 37,
        "height": 19,
        "sections": [{"name": "便笺", "items": 4}],
    }
    assert artifact.metadata["dnaby.resources"][0]["status"] == "placeholder"
