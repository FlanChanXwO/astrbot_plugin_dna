"""渲染器共用的运行期资源解析与降级工具。"""

from __future__ import annotations

from collections.abc import Iterable

from PIL import Image, ImageDraw

from .fonts import load_runtime_font


def resources_incomplete(resources: Iterable[dict[str, str]]) -> bool:
    """判断一次渲染是否使用了 placeholder 或不完整 fallback。"""

    def is_incomplete(item: dict[str, str]) -> bool:
        # 新记录显式保存 incomplete；旧 renderer 只有 status 时，fallback/missing
        # 也必须按降级处理，避免图片已生成却被误写入完整缓存。
        explicit = item.get("incomplete")
        if explicit in {"true", "false"}:
            return explicit == "true"
        return item.get("status") in {"fallback", "missing", "placeholder"}

    return any(is_incomplete(item) for item in resources)


def placeholder_image(size: tuple[int, int], label: str) -> Image.Image:
    """生成稳定的小占位图，避免缺失资源时再次触碰文件系统。"""

    width, height = size
    image = Image.new("RGBA", (max(1, width), max(1, height)), (232, 236, 242, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(133, 145, 164, 255), width=2)
    draw.text((8, 8), label, fill=(74, 83, 99, 255), font=load_runtime_font(14))
    return image






__all__ = [
    "placeholder_image",
    "resources_incomplete",
]
