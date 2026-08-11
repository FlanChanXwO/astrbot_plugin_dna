"""运行期私有资源字体加载。"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont


def load_runtime_font(
    font_path: Path | None,
    size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载已验证资源根中的字体；资源缺失时使用 Pillow 默认字体。"""

    if font_path is not None:
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


__all__ = ["load_runtime_font"]
