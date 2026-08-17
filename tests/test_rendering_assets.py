from __future__ import annotations

import base64
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from dnaby.rendering import (
    AssetRenderError,
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    to_data_uri,
    unicode_font_data_uris,
)


def test_data_uri_inlines_local_image_and_font(tmp_path: Path) -> None:
    image_path = tmp_path / "texture.png"
    image_path.write_bytes(b"image-bytes")
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"font-bytes")

    image_uri = image_data_uri(image_path)
    font_uri = font_data_uri(font_path)

    assert image_uri.startswith("data:image/png;base64,")
    assert font_uri.startswith("data:font/ttf;base64,")
    assert base64.b64decode(image_uri.rsplit(",", 1)[1]) == b"image-bytes"
    assert base64.b64decode(font_uri.rsplit(",", 1)[1]) == b"font-bytes"
    assert str(image_path) not in image_uri
    assert str(font_path) not in font_uri

    jpeg_path = tmp_path / "photo.jpg"
    jpeg_path.write_bytes(b"jpeg-bytes")
    assert image_data_uri(jpeg_path).startswith("data:image/jpeg;base64,")


def test_data_uri_supports_downloaded_bytes_and_pil_preprocessing() -> None:
    assert to_data_uri(b"remote-image", media_type="image/webp").startswith("data:image/webp;base64,")

    image = Image.new("RGB", (2, 1), "red")
    uri = pil_image_data_uri(image)
    assert uri.startswith("data:image/png;base64,")


def test_html_font_keeps_requested_family_and_uses_matching_woff2(tmp_path: Path) -> None:
    requested = tmp_path / "arial-unicode-ms-bold.ttf"
    requested.write_bytes(b"unicode-ttf")
    (tmp_path / "arial-unicode-ms-bold.woff2").write_bytes(b"unicode-woff2")
    (tmp_path / "dna_fonts.ttf").write_bytes(b"legacy-ttf")
    (tmp_path / "dna_fonts.woff2").write_bytes(b"legacy-woff2")

    uri = font_data_uri(requested)

    assert uri.startswith("data:font/woff2;base64,")
    assert base64.b64decode(uri.rsplit(",", 1)[1]) == b"unicode-woff2"


def test_unicode_font_only_loads_fallback_for_uncommon_glyphs(tmp_path: Path) -> None:
    requested = tmp_path / "unicode.ttf"
    requested.write_bytes(b"ttf")
    (tmp_path / "unicode.woff2").write_bytes(b"primary")
    (tmp_path / "unicode-fallback.woff2").write_bytes(b"fallback")

    primary, fallback = unicode_font_data_uris(requested, "常用中文 ABC ✦")
    assert base64.b64decode(primary.rsplit(",", 1)[1]) == b"primary"
    assert fallback is None

    _, fallback = unicode_font_data_uris(requested, "扩展字𠀀")
    assert fallback is not None
    assert base64.b64decode(fallback.rsplit(",", 1)[1]) == b"fallback"


def test_optimized_image_data_uri_crops_resizes_and_encodes(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    Image.new("RGB", (400, 100), "red").save(source)

    uri = optimized_image_data_uri(
        source,
        size=(80, 80),
        crop=True,
        image_format="JPEG",
        quality=85,
    )

    assert uri.startswith("data:image/jpeg;base64,")
    image_bytes = base64.b64decode(uri.rsplit(",", 1)[1])
    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.size == (80, 80)
        assert image.format == "JPEG"


def test_path_data_uri_cache_uses_mtime_and_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "asset.png"
    source.write_bytes(b"first")
    calls = 0
    original = Path.read_bytes

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    first = image_data_uri(source)
    second = image_data_uri(source)
    assert first == second
    assert calls == 1

    source.write_bytes(b"second-content")
    third = image_data_uri(source)
    assert third != first
    assert calls == 2


def test_data_uri_rejects_urls_and_unreadable_assets(tmp_path: Path) -> None:
    with pytest.raises(AssetRenderError) as url_error:
        to_data_uri("https://example.invalid/card.png")  # type: ignore[arg-type]
    assert url_error.value.kind == "asset"

    with pytest.raises(AssetRenderError) as read_error:
        image_data_uri(tmp_path / "missing.png")
    assert read_error.value.kind == "asset"


def test_shared_layout_macro_resets_margin_and_keeps_css_width() -> None:
    template_dir = Path(__file__).parents[1] / "dnaby" / "templates"
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    template = environment.from_string(
        "{% from 'cards/macros/layout.html.j2' import card_shell, avatar_title, divider, footer %}"
        "{% call card_shell(800, 320) %}{{ avatar_title('', '标题', '副标题') }}"
        "{{ divider() }}{{ footer('页脚') }}{% endcall %}"
    )

    html = template.render()
    assert "html, body { width: 100%; min-height: 100%; margin: 0; padding: 0; }" in html
    assert "width: 800px" in html
    assert "min-height: 320px" in html
    assert "标题" in html and "副标题" in html and "页脚" in html
