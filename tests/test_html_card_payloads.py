from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


@dataclass
class RenderCall:
    template_name: str
    data: dict[str, Any]
    spec: Any


class RendererSpy:
    def __init__(self) -> None:
        self.calls: list[RenderCall] = []

    async def render(self, template_name: str, data: dict[str, Any], spec: Any) -> bytes:
        self.calls.append(RenderCall(template_name, data, spec))
        return b"png"


@pytest.mark.asyncio
async def test_help_card_keeps_groups_and_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("src.infrastructure.rendering.help")
    renderer = RendererSpy()
    font_paths: list[Path] = []
    monkeypatch.setattr(module, "_RENDERER", renderer)
    monkeypatch.setattr(
        module,
        "font_data_uri",
        lambda path: font_paths.append(path) or "data:font/woff2;base64,AA==",
    )
    monkeypatch.setattr(module, "image_data_uri", lambda _: "data:image/jpeg;base64,AA==")
    monkeypatch.setattr(
        module,
        "_load_help_data",
        lambda: {"信息查询": {"data": [{"name": "日常", "eg": "日常"}]}},
    )

    assert await module.get_help() == b"png"
    call = renderer.calls[0]
    assert call.template_name == "cards/help.html.j2"
    assert call.spec.width == 2020 and call.spec.full_page is True
    assert font_paths == [module.HELP_FONT_PATH]
    assert font_paths[0].name == "MiSansVF.woff2"
    assert call.data["lines"] == [
        {"is_group": True, "name": "信息查询", "example": ""},
        {"is_group": False, "name": "日常", "example": "kk日常"},
    ]


def test_help_ambiguous_icons_match_gscore_selection() -> None:
    module = importlib.import_module("src.infrastructure.rendering.help")

    assert module._find_icon("查看UID列表").name == "UID.png"
    assert module._find_icon("基本信息卡片").name == "基本信息.png"


@pytest.mark.asyncio
async def test_announcement_list_embeds_previews_and_keeps_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("src.infrastructure.rendering.notices")
    renderer = RendererSpy()
    monkeypatch.setattr(module, "_RENDERER", renderer)
    monkeypatch.setattr(
        module,
        "unicode_font_data_uris",
        lambda _source, _text: ("data:font/woff2;base64,AA==", None),
    )
    monkeypatch.setattr(module, "image_data_uri", lambda _: "data:image/jpeg;base64,AA==")
    monkeypatch.setattr(
        module,
        "optimized_image_data_uri",
        lambda *_args, **_kwargs: "data:image/jpeg;base64,AA==",
    )
    monkeypatch.setattr(module, "pil_image_data_uri", lambda _: "data:image/png;base64,AA==")

    async def _fetch_ann_list(*, prefer_cache: bool) -> list[dict[str, str]]:
        assert prefer_cache is True
        return [{"postId": "1", "postTitle": "公告标题", "postTime": "2026-08-16", "cover": "https://x"}]

    async def _load_preview(*_: object) -> None:
        return None

    monkeypatch.setattr(module, "fetch_ann_list", _fetch_ann_list)
    monkeypatch.setattr(module, "_load_preview", _load_preview)

    assert await module.draw_ann_list_img() == b"png"
    call = renderer.calls[0]
    assert call.template_name == "cards/announcement_list.html.j2"
    assert call.spec.width == 1080 and call.spec.full_page is True
    assert call.data["height"] == 680
    assert call.data["cards"][0]["index"] == 1
    assert call.data["cards"][0]["subject"] == "公告标题"
    assert call.data["cards"][0]["preview"] is None


@pytest.mark.asyncio
async def test_sign_report_keeps_fixed_canvas_and_message_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("src.infrastructure.rendering.checkin")
    renderer = RendererSpy()
    monkeypatch.setattr(module, "_RENDERER", renderer)
    monkeypatch.setattr(module, "font_data_uri", lambda _: "data:font/ttf;base64,AA==")

    assert await module.create_sign_info_image("✅标题\n成功 2 人\n失败 1 人", theme="green") == b"png"
    call = renderer.calls[0]
    assert call.template_name == "cards/sign_report.html.j2"
    assert call.spec.width == 600 and call.spec.height == 250 and call.spec.full_page is False
    assert call.data["lines"] == ["标题", "成功 2 人", "失败 1 人"]
    assert call.data["theme_color"] == "#e6ffe6"


def test_simple_card_templates_keep_key_text_and_css_width() -> None:
    template_dir = Path(__file__).parents[1] / "src" / "templates"
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    base = {
        "background": "data:image/png;base64,AA==",
        "font": "data:font/ttf;base64,AA==",
    }
    help_html = environment.get_template("cards/help.html.j2").render(
        **base,
        width=2020,
        lines=[{"is_group": False, "name": "<命令>", "example": "示例"}],
    )
    announcement_html = environment.get_template("cards/announcement_list.html.j2").render(
        **base,
        width=1080,
        prefix="#",
        cards=[{"index": 1, "preview": None, "subject": "公告正文", "time": "今天"}],
    )
    sign_html = environment.get_template("cards/sign_report.html.j2").render(
        font=base["font"],
        width=600,
        theme_color="#ffffe6",
        lines=["签到标题"],
    )

    assert "width: 2020px" in help_html and "&lt;命令&gt;" in help_html
    assert "二重螺旋公告" in announcement_html and "公告正文" in announcement_html
    assert "min-height: 250px" in sign_html and "签到标题" in sign_html


def test_help_template_uses_legacy_group_and_item_coordinates() -> None:
    template_dir = Path(__file__).parents[1] / "src" / "templates"
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    section = {
        "name": "分组",
        "description": "说明",
        "items": [{"name": "命令", "example": "示例", "icon": "data:image/png;base64,AA=="}],
    }
    rendered = environment.get_template("cards/help.html.j2").render(
        width=2020,
        background="data:image/jpeg;base64,AA==",
        font="data:font/woff2;base64,AA==",
        banner="data:image/jpeg;base64,AA==",
        icon="data:image/png;base64,AA==",
        cag_background="data:image/png;base64,AA==",
        item_background="data:image/png;base64,AA==",
        footer="data:image/png;base64,AA==",
        subtitle="副标题",
        sections=[section, section],
    )

    assert 'style="top: 766px"' in rendered
    assert 'style="top: 1081px"' in rendered
    assert "top: 119px" in rendered
    assert "font-weight: 630" in rendered
