"""帮助卡片 HTML/T2I 渲染器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..rendering import HtmlRenderer, RenderSpec, font_data_uri, image_data_uri

HELP_DATA = Path(__file__).parent / "help.json"
BACKGROUND_PATH = Path(__file__).parent / "texture2d" / "bg.jpg"
HELP_FONT_PATH = Path(__file__).parents[1] / "utils" / "fonts" / "MiSansVF.woff2"
CARD_W = 2020
_RENDERER = HtmlRenderer()
_ICON_ALIASES = {
    # GScore 依赖目录遍历顺序处理部分命中；显式固定两个无同名文件的歧义项。
    "基本信息卡片": "基本信息.png",
    "查看UID列表": "UID.png",
}


def _load_help_data() -> dict[str, Any]:
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
    icon_dir = Path(__file__).parent / "icon_path"
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
    """渲染动态高度帮助卡片，保留旧公开函数和返回 bytes 契约。"""
    return await _RENDERER.render(
        "cards/help.html.j2",
        {
            "background": image_data_uri(BACKGROUND_PATH),
            # GScore 的 new_help 使用全局 MiSansVF，而非角色卡的 dna_fonts。
            "font": font_data_uri(HELP_FONT_PATH),
            "banner": image_data_uri(Path(__file__).parent / "texture2d" / "banner_bg.jpg"),
            "cag_background": image_data_uri(Path(__file__).parent / "texture2d" / "cag_bg.png"),
            "footer": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"),
            "icon": image_data_uri(Path(__file__).parents[2] / "ICON.png"),
            "item_background": image_data_uri(Path(__file__).parent / "texture2d" / "item.png"),
            "lines": list(_iter_help_lines(_load_help_data())),
            "sections": _help_sections(_load_help_data()),
            "subtitle": "穿过寒夜，去往有你的春天。",
            "width": CARD_W,
        },
        RenderSpec(width=CARD_W, full_page=True, image_format="jpeg"),
    )
