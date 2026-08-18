"""帮助卡片 HTML/T2I 渲染器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assets import font_data_uri, image_data_uri
from .renderer import HtmlRenderer
from .spec import RenderSpec

HELP_DATA = Path(__file__).parents[2] / "resources" / "help" / "help.json"
BACKGROUND_PATH = Path(__file__).parents[2] / "resources" / "textures" / "help" / "bg.jpg"
HELP_FONT_PATH = Path(__file__).parents[2] / "resources" / "fonts" / "MiSansVF.woff2"
ICON_DIR = Path(__file__).parents[2] / "resources" / "help" / "icon_path"

CARD_W = 2020
_RENDERER = HtmlRenderer()
_ICON_ALIASES = {
    # GScore 依赖目录遍历顺序处理部分命中；显式固定两个无同名文件的歧义项。
    "基本信息卡片": "基本信息.png",
    "查看UID列表": "UID.png",
}


def _load_help_data() -> dict[str, Any]:
    if not HELP_DATA.exists():
        fallback = Path(__file__).parents[2] / "resources" / "help.json"
        if fallback.exists():
            with fallback.open("r", encoding="utf-8") as file:
                return json.load(file)
    with HELP_DATA.open("r", encoding="utf-8") as file:
        return json.load(file)


def _iter_help_lines(plugin_help: dict[str, Any]):
    """生成保持旧分组和示例语义的帮助条目 payload。"""
    for group_name, group_data in plugin_help.items():
        yield {"is_group": True, "name": group_name, "example": ""}
        for item in group_data.get("data", []):
            yield {
                "is_group": False,
                "name": item.get("name", ""),
                "example": item.get("eg", ""),
            }


def _find_icon(name: str) -> Path:
    icon_dir = ICON_DIR
    if alias := _ICON_ALIASES.get(name):
        return icon_dir / alias
    exact = icon_dir / f"{name}.png"
    if exact.exists():
        return exact
    for path in icon_dir.glob("*.png"):
        if path.stem in name:
            return path
    return icon_dir / "通用.png"


def _help_sections(plugin_help: dict[str, Any]) -> list[dict[str, Any]]:
    """按 GScore new_help 的分组、列数和条目顺序构造模板数据。"""
    sections: list[dict[str, Any]] = []
    for name, value in plugin_help.items():
        items = []
        for command in value.get("data", []):
            item_name = str(command.get("name", ""))
            items.append(
                {
                    "example": str(command.get("eg", "")),
                    "icon": image_data_uri(_find_icon(item_name)),
                    "name": item_name,
                }
            )
        sections.append({"description": str(value.get("desc", "")), "items": items, "name": name})
    return sections


async def get_help() -> bytes:
    """使用 HTML 模板绘制帮助卡片，保留双列与三列排版结构。"""
    plugin_help = _load_help_data()
    sections = _help_sections(plugin_help)
    template_data = {
        "background": image_data_uri(BACKGROUND_PATH),
        "banner": image_data_uri(
            Path(__file__).parents[2] / "resources" / "textures" / "help" / "banner_bg.jpg",
        ),
        "cag_background": image_data_uri(
            Path(__file__).parents[2] / "resources" / "textures" / "help" / "cag_bg.png",
        ),
        "font": font_data_uri(HELP_FONT_PATH),
        "footer": image_data_uri(
            Path(__file__).parents[2] / "resources" / "textures" / "common" / "footer.png",
        ),
        "icon": image_data_uri(Path(__file__).parents[3] / "ICON.png"),
        "item_background": image_data_uri(
            Path(__file__).parents[2] / "resources" / "textures" / "help" / "item.png",
        ),
        "lines": list(_iter_help_lines(plugin_help)),
        "sections": sections,
        "subtitle": "穿过寒夜，去往有你的春天。",
        "width": CARD_W,
    }
    spec = RenderSpec(
        width=CARD_W,
        full_page=True,
        output_format="jpeg",
        quality=85,
    )
    return await _RENDERER.render("cards/help.html.j2", template_data, spec)
