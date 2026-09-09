"""T2I 截图规格。

规格只描述 CSS 画布与截图策略，不在插件内启动浏览器或实现截图逻辑。
"""

from __future__ import annotations

from numbers import Real
from typing import Literal, TypedDict


class ClipRect(TypedDict):
    """AstrBot T2I ``clip`` 参数。"""

    x: int
    y: int
    width: int
    height: int


Scale = Literal["css", "device"] | Real
ImageFormat = Literal["png", "jpeg"]


class RenderSpec:
    """单次 HTML/T2I 渲染的画布与截图参数。"""

    def __init__(
        self,
        width: int,
        height: int | None = None,
        full_page: bool = True,
        clip: ClipRect | None = None,
        scale: Scale = "css",
        image_format: ImageFormat = "png",
        output_format: ImageFormat | None = None,
        quality: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.full_page = full_page
        self.clip = clip
        self.scale = scale
        self.image_format: ImageFormat = (
            output_format if output_format is not None else image_format
        )
        self.quality = quality

        if self.width <= 0:
            raise ValueError("渲染宽度必须为正整数")
        if self.height is not None and self.height <= 0:
            raise ValueError("渲染高度必须为正整数")
        if not self.full_page and self.clip is None and self.height is None:
            raise ValueError("非 full_page 渲染必须提供 height 或 clip")
        if self.full_page and self.clip is not None:
            raise ValueError("full_page 渲染不能同时提供 clip")
        if self.image_format not in ("png", "jpeg"):
            raise ValueError(f"不支持的渲染格式: {self.image_format}")
        if self.image_format == "png" and self.quality is not None:
            raise ValueError("PNG 渲染不能设置 quality")
        if self.quality is not None and not 0 <= self.quality <= 100:
            raise ValueError("JPEG quality 必须在 0 到 100 之间")
        if self.clip is not None:
            self._validate_clip(self.clip)

    def __repr__(self) -> str:
        return (
            f"RenderSpec(width={self.width}, height={self.height}, "
            f"full_page={self.full_page}, clip={self.clip}, scale={self.scale}, "
            f"image_format={self.image_format!r}, quality={self.quality})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RenderSpec):
            return NotImplemented
        return (
            self.width == other.width
            and self.height == other.height
            and self.full_page == other.full_page
            and self.clip == other.clip
            and self.scale == other.scale
            and self.image_format == other.image_format
            and self.quality == other.quality
        )

    @staticmethod
    def _validate_clip(clip: ClipRect) -> None:
        if any(clip[key] < 0 for key in ("x", "y")):
            raise ValueError("clip 的 x/y 不能为负数")
        if any(clip[key] <= 0 for key in ("width", "height")):
            raise ValueError("clip 的 width/height 必须为正整数")

    def options(self) -> dict[str, object]:
        """生成传给 AstrBot 的 options，不包含插件私有字段。"""

        options: dict[str, object] = {
            "full_page": self.full_page,
            "type": self.image_format,
            "scale": self.scale,
            # AstrBot T2I 默认 viewport 是 800x720；显式传入画布尺寸，避免
            # 固定卡片被默认视口裁切或动态卡片被无意放大。
            "viewport_width": self.width,
        }
        if self.image_format == "jpeg":
            options["quality"] = 85 if self.quality is None else self.quality
        if self.height is not None:
            options["viewport_height"] = self.height
        if not self.full_page:
            options["clip"] = self.clip or {
                "x": 0,
                "y": 0,
                "width": self.width,
                "height": self.height,
            }
        return options


__all__ = ["ClipRect", "ImageFormat", "RenderSpec", "Scale"]
