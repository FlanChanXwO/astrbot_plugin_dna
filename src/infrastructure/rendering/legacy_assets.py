"""仅供无 resolver 兼容路径使用的本地资源常量。

正常运行期 renderer 不应读取本模块中的大型资源；注入 RuntimeAssetResolver 后会走
逻辑 key。保留这些常量只是为了兼容旧的独立 helper 和现有测试。
"""

from pathlib import Path

from PIL import Image

from .assets import (
    AssetSource,
    pil_image_data_uri,
)
from .assets import (
    font_data_uri as _font_data_uri,
)
from .assets import (
    image_data_uri as _image_data_uri,
)
from .assets import (
    optimized_image_data_uri as _optimized_image_data_uri,
)
from .assets import (
    unicode_font_data_uris as _unicode_font_data_uris,
)
from .errors import AssetRenderError
from .runtime_assets import (
    placeholder_image,
    resolved_font_data_uri,
    resolved_image_data_uri,
)

RESOURCE_ROOT = Path(__file__).parents[2] / "resources"
RESOURCES_DIR = RESOURCE_ROOT

# 仅保留少量通用装饰图作为本地 bootstrap；完整纹理由 resource snapshot 提供。
BOOTSTRAP_TEXTURE_ROOT = Path(__file__).parents[2] / "utils" / "texture2d"
COMMON_PATH = BOOTSTRAP_TEXTURE_ROOT
DETAIL_TEXT_PATH = RESOURCE_ROOT / "textures" / "detail"
ROLE_TEXT_PATH = RESOURCE_ROOT / "textures" / "role"
STAMINA_TEXT_PATH = RESOURCE_ROOT / "textures" / "stamina"
WEEKLY_TEXT_PATH = RESOURCE_ROOT / "textures" / "weekly_report"
CALENDAR_TEXT_PATH = RESOURCE_ROOT / "textures" / "calendar"
TEXT_PATH = CALENDAR_TEXT_PATH
SIGN_TEXT_PATH = RESOURCE_ROOT / "textures" / "sign"
MH_TEXT_PATH = RESOURCE_ROOT / "textures" / "mh"
ANN_TEXT_PATH = RESOURCE_ROOT / "textures" / "ann"

BACKGROUND_PATH = COMMON_PATH / "bg1.jpg"
FONT_ORIGIN_PATH = RESOURCE_ROOT / "fonts" / "dna_fonts.ttf"
UNICODE_ORIGIN_PATH = RESOURCE_ROOT / "fonts" / "arial-unicode-ms-bold.ttf"
HELP_FONT_PATH = RESOURCE_ROOT / "fonts" / "MiSansVF.woff2"

HELP_DATA = RESOURCE_ROOT / "help" / "help.json"
HELP_DATA_FALLBACK = RESOURCE_ROOT / "help.json"
HELP_ICON_DIR = RESOURCE_ROOT / "help" / "icon_path"
HELP_BACKGROUND_PATH = RESOURCE_ROOT / "textures" / "help" / "bg.jpg"
HELP_BANNER_PATH = RESOURCE_ROOT / "textures" / "help" / "banner_bg.jpg"
HELP_CAG_PATH = RESOURCE_ROOT / "textures" / "help" / "cag_bg.png"
HELP_ITEM_PATH = RESOURCE_ROOT / "textures" / "help" / "item.png"
HELP_FOOTER_PATH = COMMON_PATH / "footer.png"
PLUGIN_ICON_PATH = Path(__file__).parents[3] / "ICON.png"

OFFICIAL_AVATAR_PATH = ANN_TEXT_PATH / "dna_official_avatar.jpeg"


def _legacy_label(source: AssetSource) -> str:
    return source.name if isinstance(source, Path) else "asset"


def legacy_image_data_uri(
    source: AssetSource,
    *,
    media_type: str | None = None,
) -> str:
    """读取旧 helper 的素材；素材已外置时返回可见 placeholder。"""

    try:
        return _image_data_uri(source, media_type=media_type)
    except (AssetRenderError, OSError, ValueError):
        legacy_path = source if isinstance(source, Path) else None
        return resolved_image_data_uri(
            None,
            f"legacy.image:{_legacy_label(source)}",
            legacy_path=legacy_path,
            label=_legacy_label(source),
        )[0]


def legacy_font_data_uri(
    source: AssetSource,
    *,
    media_type: str | None = None,
) -> str:
    """读取旧 helper 的字体；完整字体缺失时交给 CSS fallback。"""

    try:
        return _font_data_uri(source, media_type=media_type)
    except (AssetRenderError, OSError, ValueError):
        legacy_path = source if isinstance(source, Path) else None
        return resolved_font_data_uri(
            None,
            "legacy.font",
            legacy_path=legacy_path,
        )[0]


def legacy_optimized_image_data_uri(
    source: Path,
    *,
    size: tuple[int, int],
    crop: bool = False,
    image_format: str = "WEBP",
    quality: int = 85,
) -> str:
    """兼容旧尺寸优化 helper；外置素材未同步时返回尺寸稳定的 placeholder。"""

    try:
        return _optimized_image_data_uri(
            source,
            size=size,
            crop=crop,
            image_format=image_format,
            quality=quality,
        )
    except (AssetRenderError, OSError, ValueError):
        image = placeholder_image(size, _legacy_label(source))
        if image_format.upper() in {"JPEG", "JPG"}:
            image = image.convert("RGB")
        return pil_image_data_uri(image, image_format=image_format)


def legacy_unicode_font_data_uris(source: Path, text: str) -> tuple[str, str | None]:
    """兼容旧中文字体拆分 helper；字体外置时返回 CSS fallback。"""

    try:
        return _unicode_font_data_uris(source, text)
    except (AssetRenderError, OSError, ValueError):
        return legacy_font_data_uri(source), None


def open_legacy_image(
    source: Path,
    *,
    size: tuple[int, int],
    label: str,
) -> Image.Image:
    """旧 PIL helper 的安全读取边界，避免外置素材缺失阻断基础图片命令。"""

    try:
        with Image.open(source) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError):
        return placeholder_image(size, label)

__all__ = [
    "ANN_TEXT_PATH",
    "BACKGROUND_PATH",
    "CALENDAR_TEXT_PATH",
    "COMMON_PATH",
    "DETAIL_TEXT_PATH",
    "FONT_ORIGIN_PATH",
    "HELP_BACKGROUND_PATH",
    "HELP_BANNER_PATH",
    "HELP_CAG_PATH",
    "HELP_DATA",
    "HELP_DATA_FALLBACK",
    "HELP_FONT_PATH",
    "HELP_FOOTER_PATH",
    "HELP_ICON_DIR",
    "HELP_ITEM_PATH",
    "MH_TEXT_PATH",
    "OFFICIAL_AVATAR_PATH",
    "PLUGIN_ICON_PATH",
    "RESOURCES_DIR",
    "RESOURCE_ROOT",
    "ROLE_TEXT_PATH",
    "SIGN_TEXT_PATH",
    "STAMINA_TEXT_PATH",
    "TEXT_PATH",
    "UNICODE_ORIGIN_PATH",
    "WEEKLY_TEXT_PATH",
    "legacy_font_data_uri",
    "legacy_image_data_uri",
    "legacy_optimized_image_data_uri",
    "legacy_unicode_font_data_uris",
    "open_legacy_image",
]
