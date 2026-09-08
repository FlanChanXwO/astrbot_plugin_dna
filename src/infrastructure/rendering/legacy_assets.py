"""仅供无 resolver 兼容路径使用的本地资源常量。

正常运行期 renderer 不应读取本模块中的大型资源；注入 RuntimeAssetResolver 后会走
逻辑 key。保留这些常量只是为了兼容旧的独立 helper 和现有测试。
"""

from pathlib import Path

RESOURCE_ROOT = Path(__file__).parents[2] / "resources"
RESOURCES_DIR = RESOURCE_ROOT

COMMON_PATH = RESOURCE_ROOT / "textures" / "common"
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
]
