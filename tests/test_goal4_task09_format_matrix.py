"""Goal 4 / Task 09：T2I 格式矩阵与发布体积回归。"""

from __future__ import annotations
from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image
from src.infrastructure.rendering.artifact import RenderedArtifact
from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.infrastructure.rendering.encyclopedia import EncyclopediaRenderer
from src.infrastructure.rendering.notices import NoticesRenderer
from src.infrastructure.rendering.player import PlayerRenderer, ResourceMap
from src.infrastructure.rendering.renderer import HtmlRenderer
from src.infrastructure.rendering.spec import RenderSpec
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore


def _image_bytes(media_type: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (43, 29), "#6284a3").save(
        buffer, format="JPEG" if media_type == "image/jpeg" else "PNG"
    )
    return buffer.getvalue()


@pytest.mark.parametrize("media_type", ["image/jpeg", "image/png"])
def test_artifact_format_matrix_preserves_t2i_bytes(media_type: str) -> None:
    payload = _image_bytes(media_type)
    artifact = RenderedArtifact.from_bytes(payload, media_type=media_type)  # type: ignore[arg-type]
    assert artifact.data == payload
    assert artifact.media_type == media_type
    assert (artifact.width, artifact.height) == (43, 29)


@pytest.mark.parametrize("kind", ["player", "encyclopedia", "notices"])
def test_renderer_writer_matrix_keeps_original_jpeg_bytes(
    tmp_path: Path, kind: str
) -> None:
    payload = _image_bytes("image/jpeg")
    if kind == "player":
        renderer = PlayerRenderer(tmp_path / kind, ResourceMap())
        rendered = renderer._write(payload, lines=["玩家"], resources=[], sections=[])
    elif kind == "encyclopedia":
        renderer = EncyclopediaRenderer(
            tmp_path / kind, EncyclopediaResourceStore.from_root(tmp_path / "resources")
        )
        rendered = renderer._write(payload, lines=["便笺"], resources=[], sections=[])
    else:
        renderer = NoticesRenderer(
            tmp_path / kind, EncyclopediaResourceStore.from_root(tmp_path / "resources")
        )
        rendered = renderer._write_cached(
            payload, lines=["公告"], resources=[], sections=[]
        )
    assert rendered.path.read_bytes() == payload
    assert rendered.path.suffix == ".jpg"
    assert read_rendered_artifact(rendered.path).data == payload


@pytest.mark.asyncio
async def test_html_renderer_does_not_decode_or_reencode_t2i_result() -> None:
    payload = _image_bytes("image/jpeg")

    class T2I:
        async def render_custom_template(self, **_: object) -> bytes:
            return payload

    result = await HtmlRenderer(t2i=T2I()).render(
        "cards/help.html.j2",
        {"title": "帮助", "sections": [], "width": 600},
        RenderSpec(width=600, height=250, full_page=False, output_format="jpeg"),
    )
    assert result == payload
