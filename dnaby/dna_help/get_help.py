"""原生帮助卡片渲染器：替代 gsucore ``get_new_help``。

读取 ``help.json``，用 PIL 绘制帮助卡片，返回 PNG bytes。
"""

import json
from pathlib import Path

from PIL import ImageDraw

from ..utils.fonts.dna_fonts import dna_font_20, dna_font_25
from ..utils.image import get_dna_bg
from ..utils.image_utils import convert_img

HELP_DATA = Path(__file__).parent / "help.json"

CARD_W = 800

COLOR_TITLE = (250, 250, 210)  # 浅金黄
COLOR_TEXT = (255, 255, 255)
COLOR_GRAY = (200, 200, 200)

PADDING_TOP = 40
PADDING_BOTTOM = 40
TITLE_H = 40
TITLE_GAP = 18
LINE_H = 30
LINE_GAP = 10


def _load_help_data() -> dict:
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        return json.load(file)


def _iter_help_lines(plugin_help: dict):
    """yield (name, eg, is_group)。"""
    for group_name, group_data in plugin_help.items():
        yield group_name, "", True
        for item in group_data.get("data", []):
            yield item.get("name", ""), item.get("eg", ""), False


def _calc_height(lines: list) -> int:
    h = PADDING_TOP + PADDING_BOTTOM
    for _, _, is_group in lines:
        if is_group:
            h += TITLE_H + TITLE_GAP
        else:
            h += LINE_H + LINE_GAP
    return h


async def get_help() -> bytes:
    """渲染帮助卡片（PIL），返回 PNG bytes。"""
    plugin_help = _load_help_data()
    lines = list(_iter_help_lines(plugin_help))

    img = get_dna_bg(CARD_W, _calc_height(lines), "bg")
    draw = ImageDraw.Draw(img)

    y = PADDING_TOP
    for name, eg, is_group in lines:
        if is_group:
            draw.text((40, y), name, COLOR_TITLE, dna_font_25, "lm")
            y += TITLE_H + TITLE_GAP
        else:
            text = f"{name} ({eg})" if eg else name
            draw.text((60, y), text, COLOR_TEXT, dna_font_20, "lm")
            y += LINE_H + LINE_GAP

    return await convert_img(img)
