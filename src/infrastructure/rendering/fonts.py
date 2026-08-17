"""运行期私有资源字体加载。"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

BUNDLED_FONT_PATH = Path(__file__).resolve().parents[3] / "dnaby" / "utils" / "fonts" / "dna_fonts.ttf"


def load_runtime_font(
    font_path: Path | None,
    size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载运行资源字体；未注入时使用插件内置中文字体。"""

    if font_path is not None:
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.truetype(str(BUNDLED_FONT_PATH), size=size)


__all__ = ["load_runtime_font"]
