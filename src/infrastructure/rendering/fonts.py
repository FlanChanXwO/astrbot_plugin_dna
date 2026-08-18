"""运行期私有资源字体加载。"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

BUNDLED_FONT_PATH = Path(__file__).resolve().parents[2] / "resources" / "fonts" / "dna_fonts.ttf"


def load_runtime_font(
    font_path: Path | int | None = None,
    size: int | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载运行资源字体；未注入时使用插件内置中文字体。"""

    if isinstance(font_path, int) and size is None:
        size = font_path
        font_path = None
    actual_size = size if size is not None else 16
    if font_path is not None and isinstance(font_path, Path) and font_path.is_file():
        return ImageFont.truetype(str(font_path), size=actual_size)
    return ImageFont.truetype(str(BUNDLED_FONT_PATH), size=actual_size)


__all__ = ["BUNDLED_FONT_PATH", "load_runtime_font"]
