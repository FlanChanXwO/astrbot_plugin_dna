"""运行期私有资源字体加载。"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

BUNDLED_FONT_PATH = Path(__file__).resolve().parents[2] / "resources" / "fonts" / "dna_fonts.ttf"


def load_runtime_font(
    font_path: Path | int | None = None,
    size: int | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载运行资源字体；资源缺失时返回 Pillow 的内置字体。"""

    if isinstance(font_path, int) and size is None:
        size = font_path
        font_path = None
    actual_size = size if size is not None else 16
    candidates: tuple[Path, ...] = tuple(
        path
        for path in (font_path, BUNDLED_FONT_PATH)
        if isinstance(path, Path) and path.is_file()
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=actual_size)
        except (OSError, ValueError):
            # 字体可能已被瘦身删除或损坏；Pillow 内置字体保证简化卡片仍可出图。
            continue
    return ImageFont.load_default()


__all__ = ["BUNDLED_FONT_PATH", "load_runtime_font"]
