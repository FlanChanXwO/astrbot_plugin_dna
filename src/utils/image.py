from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from astrbot.api import logger
from PIL import Image, ImageDraw

from ..infrastructure.data_layout import default_runtime_data_layout
from . import image_utils
from .image_utils import (
    ImageFetchError,
    download,
)

if TYPE_CHECKING:
    from ..infrastructure.resources.resolver import AssetDownloader

# Gold & Earth Tones
COLOR_LIGHT_GOLDENROD = (250, 250, 210)  # 浅金黄色
COLOR_PALE_GOLDENROD = (238, 232, 170)  # 淡金黄色的
COLOR_KHAKI = (240, 230, 140)  # 黄褐色
COLOR_GOLDENROD = (218, 165, 32)  # 金毛
COLOR_GOLD = (255, 215, 0)  # 金
COLOR_ORANGE = (255, 165, 0)  # 橙子
COLOR_DARK_ORANGE = (255, 140, 0)  # 深橙色
COLOR_PERU = (205, 133, 63)  # 秘鲁
COLOR_CHOCOLATE = (210, 105, 30)  # 巧克力
COLOR_SADDLE_BROWN = (139, 69, 19)  # 马鞍棕色
COLOR_SIENNA = (160, 82, 45)  # 赭色

# Red & Pink Tones
COLOR_LIGHT_SALMON = (255, 160, 122)  # 浅鲑红 / Lightsalmon #FFA07A
COLOR_SALMON = (250, 128, 114)  # 三文鱼 / Salmon #FA8072
COLOR_DARK_SALMON = (233, 150, 122)  # 黑鲑 / Dark Salmon #E9967A
COLOR_LIGHT_CORAL = (240, 128, 128)  # 轻珊瑚 / Light Coral #F08080
COLOR_INDIAN_RED = (205, 92, 92)  # 印度红 / Indian Red #CD5C5C
COLOR_CRIMSON = (220, 20, 60)  # 赤红 / Crimson #DC143C
COLOR_FIRE_BRICK = (178, 34, 34)  # 耐火砖 / Fire Brick #B22222
COLOR_RED = (255, 0, 0)  # 红色 / Red #FF0000
COLOR_DARK_RED = (139, 0, 0)  # 深红 / Dark Red #8B0000
COLOR_MAROON = (128, 0, 0)  # 栗色 / Maroon #800000
COLOR_TOMATO = (255, 99, 71)  # 番茄 / Tomato #FF6347
COLOR_ORANGE_RED = (255, 69, 0)  # 橙红 / Orange Red #FF4500
COLOR_PALE_VIOLET_RED = (219, 112, 147)  # 泛紫红 / Pale Violet Red #DB7093

# Basic Colors
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (128, 128, 128)
COLOR_LIGHT_GRAY = (230, 230, 230)
COLOR_GREEN = (76, 175, 80)
COLOR_BLUE = (30, 40, 60)
COLOR_PURPLE = (138, 43, 226)


Color = str | tuple[int, int, int] | tuple[int, int, int, int]


def _normalize_paint_img(image: Image.Image) -> Image.Image:
    paint_size = 1320
    normalize_threshold = 1400

    if image.width <= normalize_threshold and image.height <= normalize_threshold:
        return image

    side = min(image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side)).resize(
        (paint_size, paint_size),
        Image.Resampling.LANCZOS,
    )


def _load_cached_image(path: Path) -> Image.Image | None:
    """只读取受控目录中的完整图片，拒绝损坏文件和符号链接。"""

    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.convert("RGBA")
    except (OSError, SyntaxError, ValueError):
        return None


async def download_pic_from_url(
    path: Path,
    pic_url: str,
    size: tuple[int, int] | None = None,
    name: str | None = None,
    *,
    downloader: AssetDownloader | None = None,
) -> Image.Image:
    path.mkdir(parents=True, exist_ok=True)

    if name is None:
        name = pic_url.split("/")[-1]
    _path = path / name
    _ = await image_utils.download(
        pic_url,
        path,
        name,
        tag="DNA",
        downloader=downloader,
    )

    img = Image.open(_path)
    if size:
        img = img.resize(size)

    return img.convert("RGBA")


async def _download_optional_image(
    path: Path,
    name: str,
    pic_url: str,
    *,
    downloader: AssetDownloader | None = None,
) -> bool:
    """下载可退化卡片素材；失败只允许本次内存占位，不写假缓存。"""

    try:
        await download(
            pic_url,
            path,
            name,
            tag="DNA",
            downloader=downloader,
        )
    except (ImageFetchError, httpx.HTTPError):
        # 角色卡已有明确的内存占位语义，严格图片链路仍直接使用 download()。
        return False
    return True


async def get_skill_img(
    char_id: str | int, skill_name: str, pic_url: str | None = None
) -> Image.Image:
    char_skill_dir = default_runtime_data_layout().cache_skill_dir / str(char_id)
    char_skill_dir.mkdir(parents=True, exist_ok=True)

    skill_name = skill_name.strip()
    name = f"skill_{skill_name}.png"
    skill_path = char_skill_dir / name
    if pic_url and not await _download_optional_image(char_skill_dir, name, pic_url):
        return Image.new("RGBA", (128, 128))
    image = _load_cached_image(skill_path)
    if image is None:
        return Image.new("RGBA", (128, 128))

    return image


async def get_avatar_img(
    char_id: str | int,
    pic_url: str | None = None,
    *,
    avatar_path: Path | None = None,
    downloader: AssetDownloader | None = None,
) -> Image.Image:
    char_avatar_dir = (
        default_runtime_data_layout().cache_game_avatar_dir
        if avatar_path is None
        else Path(avatar_path)
    )
    char_avatar_dir.mkdir(parents=True, exist_ok=True)

    name = f"avatar_{char_id}.png"
    cached_avatar_path = char_avatar_dir / name
    if pic_url and not await _download_optional_image(
        char_avatar_dir,
        name,
        pic_url,
        downloader=downloader,
    ):
        return Image.new("RGBA", (256, 256))
    image = _load_cached_image(cached_avatar_path)
    if image is None:
        return Image.new("RGBA", (256, 256))

    return image


async def get_weapon_img(
    weapon_id: str | int, pic_url: str | None = None
) -> Image.Image:
    weapon_dir = default_runtime_data_layout().cache_weapon_dir
    weapon_dir.mkdir(parents=True, exist_ok=True)

    name = f"weapon_{weapon_id}.png"
    weapon_path = weapon_dir / name
    if pic_url and not await _download_optional_image(weapon_dir, name, pic_url):
        return Image.new("RGBA", (256, 256))
    image = _load_cached_image(weapon_path)
    if image is None:
        return Image.new("RGBA", (256, 256))

    return image.resize((256, 256))


async def get_attr_img(
    attr_id: str | int | None = None, pic_url: str | None = None
) -> Image.Image:
    if attr_id is None:
        if pic_url:
            attr_id = pic_url.split("/")[-1].split(".")[0]
        else:
            raise ValueError("attr_id 和 pic_url 不能同时为空")

    attr_dir = default_runtime_data_layout().cache_attr_dir
    attr_dir.mkdir(parents=True, exist_ok=True)

    name = f"attr_{attr_id}.png"
    attr_path = attr_dir / name
    if pic_url and not await _download_optional_image(attr_dir, name, pic_url):
        return Image.new("RGBA", (128, 128))
    image = _load_cached_image(attr_path)
    if image is None:
        return Image.new("RGBA", (128, 128))

    return image


async def get_weapon_attr_img(
    attr_id: str | int | None = None, pic_url: str | None = None
) -> Image.Image:
    if attr_id is None:
        if pic_url:
            attr_id = pic_url.split("/")[-1].split(".")[0]
        else:
            raise ValueError("attr_id 和 pic_url 不能同时为空")

    attr_dir = default_runtime_data_layout().cache_weapon_attr_dir
    attr_dir.mkdir(parents=True, exist_ok=True)

    name = f"attr_{attr_id}.png"
    attr_path = attr_dir / name
    if pic_url and not await _download_optional_image(attr_dir, name, pic_url):
        return Image.new("RGBA", (128, 128))
    image = _load_cached_image(attr_path)
    if image is None:
        return Image.new("RGBA", (128, 128))

    return image


async def get_paint_img(char_id: str | int, pic_url: str | None = None) -> Image.Image:
    paint_dir = default_runtime_data_layout().cache_paint_dir
    paint_dir.mkdir(parents=True, exist_ok=True)

    name = f"paint_{char_id}.png"
    paint_path = paint_dir / name
    if pic_url and not await _download_optional_image(paint_dir, name, pic_url):
        return Image.new("RGBA", (1320, 1320))
    image = _load_cached_image(paint_path)
    if image is None:
        return Image.new("RGBA", (1320, 1320))

    return _normalize_paint_img(image)


async def get_mod_img(mod_id: str | int, pic_url: str | None = None) -> Image.Image:
    mod_dir = default_runtime_data_layout().cache_mod_dir
    mod_dir.mkdir(parents=True, exist_ok=True)

    name = f"mod_{mod_id}.png"
    mod_path = mod_dir / name
    if pic_url and not await _download_optional_image(mod_dir, name, pic_url):
        return Image.new("RGBA", (256, 256))
    image = _load_cached_image(mod_path)
    if image is None:
        return Image.new("RGBA", (256, 256))

    return image


class SmoothDrawer:
    """通用抗锯齿绘制工具"""

    def __init__(self, scale: int = 4):
        self.scale: int = scale

    def rounded_rectangle(
        self,
        xy: tuple[int, ...],
        radius: int,
        fill: Color | None = None,
        outline: Color | None = None,
        width: int = 0,
        target: Image.Image | None = None,
    ) -> None:
        if len(xy) == 4:
            # 边界框坐标 (x0, y0, x1, y1)
            x0, y0, x1, y1 = xy
            w = abs(x1 - x0)
            h = abs(y1 - y0)
            # 如果提供了目标图片，使用边界框的实际坐标
            paste_x, paste_y = min(x0, x1), min(y0, y1)
        elif len(xy) == 2:
            # 尺寸 (width, height) - 向后兼容
            w, h = xy
            paste_x, paste_y = 0, 0
        else:
            raise ValueError(
                f"xy 参数必须是 2 或 4 个元素的元组，当前为 {len(xy)} 个元素"
            )

        if h <= 0 or w <= 0:
            return

        large = Image.new("RGBA", (w * self.scale, h * self.scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(large)

        # 绘制
        draw.rounded_rectangle(
            (0, 0, w * self.scale, h * self.scale),
            radius=radius * self.scale,
            fill=fill,
            outline=outline,
            width=width * self.scale,
        )

        result = large.resize((w, h))

        if target is not None:
            target.alpha_composite(result, (paste_x, paste_y))
            return


def get_smooth_drawer(scale: int = 4) -> SmoothDrawer:
    return SmoothDrawer(scale=scale)


def save_webp_img(
    image: Image.Image, path: Path, quality: int = 90, method: int = 4
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
    image.convert(mode).save(path, "WEBP", quality=quality, method=method)


def compress_to_webp(
    image_path: Path, quality: int = 90, delete_original: bool = True
) -> tuple[bool, Path]:
    try:
        if not image_path.exists():
            logger.warning(f"图片不存在: {image_path}")
            return False, image_path

        if image_path.suffix.lower() == ".webp":
            logger.info(f"图片已经是webp格式: {image_path}")
            return False, image_path

        webp_path = image_path.with_suffix(".webp")
        orig_size = image_path.stat().st_size
        with Image.open(image_path) as image:
            save_webp_img(image, webp_path, quality=quality)
        webp_size = webp_path.stat().st_size

        if webp_size >= orig_size:
            webp_path.unlink(missing_ok=True)
            logger.info(f"图片 {image_path.name} WebP 压缩后文件更大，保留原文件")
            return False, image_path

        compression_ratio = (1 - webp_size / orig_size) * 100 if orig_size > 0 else 0
        logger.info(
            " ".join(
                [
                    f"图片 {image_path.name} 压缩为webp格式 (质量: {quality}),",
                    f"压缩率: {compression_ratio:.2f}%,",
                    f"大小: {orig_size / 1024:.1f}KB -> {webp_size / 1024:.1f}KB",
                ]
            )
        )

        if delete_original:
            image_path.unlink()
            logger.info(f"原图片已删除: {image_path}")

        return True, webp_path

    except (OSError, ValueError, KeyError) as e:
        logger.error(f"压缩图片为webp格式失败: {e}")
        return False, image_path
