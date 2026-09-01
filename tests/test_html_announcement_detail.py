from __future__ import annotations

import inspect
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from src.infrastructure.rendering import notices as ann_card
from src.modules.encyclopedia.service import EncyclopediaService

TEMPLATE_DIR = Path(__file__).parents[1] / "src" / "templates"


def _jpeg(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "navy").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_announcement_detail_keeps_html_payload_and_multi_page_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any], Any]] = []

    class Renderer:
        async def render(self, template: str, data: dict[str, Any], spec: Any) -> bytes:
            calls.append((template, data, spec))
            return _jpeg(1080, ann_card.PAGE_LIMIT + 25)

    async def fetch_posts(*, prefer_cache: bool) -> list[dict[str, object]]:
        assert prefer_cache is True
        return [{"postId": "7", "postTitle": "列表标题", "postTime": "2026-08-16"}]

    async def get_detail(_: str) -> SimpleNamespace:
        return SimpleNamespace(
            is_success=True,
            data={
                "postDetail": {
                    "postTitle": "完整公告标题<script>",
                    "postTime": "2026-08-16",
                    "postContent": [object()],
                }
            },
        )

    async def detail_image(*_: object) -> Image.Image:
        return Image.new("RGB", (20, 30), "red")

    async def qr_code(*_: object) -> Image.Image:
        return Image.new("RGB", (10, 10), "white")

    monkeypatch.setattr(ann_card, "_RENDERER", Renderer())
    monkeypatch.setattr(ann_card, "fetch_ann_list", fetch_posts)
    monkeypatch.setattr(ann_card.dna_api, "get_post_detail", get_detail)
    monkeypatch.setattr(
        ann_card,
        "extract_blocks",
        lambda _: [
            ("text", "完整正文<script>"),
            ("image", "https://asset.invalid/image"),
        ],
    )
    monkeypatch.setattr(ann_card, "_load_detail_image", detail_image)
    monkeypatch.setattr(ann_card, "load_qr_code", qr_code)
    monkeypatch.setattr(
        ann_card, "_load_avatar", lambda _: Image.new("RGB", (10, 10), "blue")
    )
    monkeypatch.setattr(
        ann_card,
        "unicode_font_data_uris",
        lambda _source, _text: ("data:font/woff2;base64,AA==", None),
    )
    monkeypatch.setattr(
        ann_card, "image_data_uri", lambda _: "data:image/jpeg;base64,AA=="
    )
    monkeypatch.setattr(
        ann_card, "pil_image_data_uri", lambda _: "data:image/png;base64,AA=="
    )

    result = await ann_card.draw_ann_detail_img("7")

    assert isinstance(result, list) and len(result) == 2
    assert Image.open(BytesIO(result[0])).size == (1080, ann_card.PAGE_LIMIT)
    assert Image.open(BytesIO(result[1])).size == (1080, 25)
    template, data, spec = calls[0]
    assert template == "cards/announcement_detail.html.j2"
    assert spec.width == 1080 and spec.full_page is True
    assert data["subject"] == "完整公告标题<script>"
    assert data["blocks"] == [
        {"kind": "text", "value": "完整正文<script>"},
        {"kind": "image", "value": "data:image/png;base64,AA=="},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("height", [5999, ann_card.PAGE_LIMIT])
async def test_announcement_page_split_preserves_single_page_bytes(
    height: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = _jpeg(1080, height)

    def fail_image_open(*_: object, **__: object) -> None:
        raise AssertionError("普通公告不应经过 Pillow")

    monkeypatch.setattr(ann_card.Image, "open", fail_image_open)
    assert await ann_card._split_rendered_pages(rendered) is rendered


@pytest.mark.asyncio
async def test_announcement_page_split_uses_jpeg_only_for_over_limit_pages() -> None:
    rendered = _jpeg(1080, ann_card.PAGE_LIMIT + 25)
    pages = await ann_card._split_rendered_pages(rendered)

    assert isinstance(pages, list) and len(pages) == 2
    assert [Image.open(BytesIO(page)).size for page in pages] == [
        (1080, ann_card.PAGE_LIMIT),
        (1080, 25),
    ]
    assert all(page.startswith(b"\xff\xd8\xff") for page in pages)


def test_announcement_detail_template_escapes_and_keeps_complete_content() -> None:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )
    image = "data:image/png;base64,AA=="
    html = environment.get_template("cards/announcement_detail.html.j2").render(
        avatar=image,
        background=image,
        blocks=[
            {"kind": "text", "value": ">>> 很长且不应截断的公告正文<script>"},
            {"kind": "image", "value": image},
        ],
        font="data:font/ttf;base64,AA==",
        qr=image,
        subject="公告标题<script>",
        time_text="2026-08-16 12:00",
        width=1080,
    )

    assert "width: 1080px" in html
    assert "很长且不应截断的公告正文&lt;script&gt;" in html
    assert "公告标题&lt;script&gt;" in html
    assert "<script>" not in html
    assert html.count("data:image/png;base64,AA==") >= 3


def test_guide_and_wiki_keep_original_image_send_path() -> None:
    service_source = inspect.getsource(EncyclopediaService)

    assert "guide" in service_source
    assert "wiki" in service_source
    assert "ImageResponse" in service_source
