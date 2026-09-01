"""Goal 4 / Task 02：T2I artifact 与标准库图片检查器的 Red 测试。"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from src.infrastructure.rendering.artifact import RenderedArtifact
from src.infrastructure.rendering.image_inspector import inspect_image


def _image_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (7, 11), "#336699").save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("media_type", "suffix", "image_format"),
    [
        ("image/jpeg", ".jpg", "JPEG"),
        ("image/png", ".png", "PNG"),
    ],
)
def test_inspect_image_reads_dimensions_without_pillow_contract(
    media_type: str,
    suffix: str,
    image_format: str,
) -> None:
    payload = _image_bytes(image_format)

    inspected = inspect_image(payload, media_type=media_type)

    assert inspected.media_type == media_type
    assert inspected.suffix == suffix
    assert inspected.width == 7
    assert inspected.height == 11


def test_rendered_artifact_preserves_original_bytes_and_rejects_mismatch() -> None:
    payload = _image_bytes("JPEG")

    artifact = RenderedArtifact.from_bytes(payload, media_type="image/jpeg")

    assert artifact.data is payload
    assert artifact.media_type == "image/jpeg"
    assert artifact.suffix == ".jpg"
    assert artifact.width == 7
    assert artifact.height == 11
    with pytest.raises(ValueError, match="格式不匹配"):
        RenderedArtifact.from_bytes(payload, media_type="image/png")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html>T2I upstream error</html>",
        _image_bytes("JPEG")[:-2],
        _image_bytes("PNG")[:-12],
    ],
)
def test_inspector_rejects_empty_html_and_truncated_images(payload: bytes) -> None:
    with pytest.raises(ValueError):
        inspect_image(payload, media_type="image/jpeg")



def test_inspector_does_not_call_pillow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _image_bytes("JPEG")

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("标准库图片检查器不应调用 Pillow")

    monkeypatch.setattr("PIL.Image.open", fail)
    monkeypatch.setattr("PIL.Image.Image.save", fail)

    inspected = inspect_image(payload, media_type="image/jpeg")

    assert inspected.width == 7
    assert inspected.height == 11
