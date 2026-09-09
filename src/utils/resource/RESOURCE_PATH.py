import base64
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# 数据根目录：data/plugin_data/astrbot_plugin_dna
# （可用环境变量 DNABY_DATA_DIR 覆盖，测试用）
if os.environ.get("DNABY_DATA_DIR"):
    MAIN_PATH = Path(os.environ["DNABY_DATA_DIR"])
else:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    MAIN_PATH = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_dna"

# 配置文件（已并入 AstrBotConfig，保留路径定义便于回看）
CONFIG_PATH = MAIN_PATH / "config.json"
SIGN_CONFIG_PATH = MAIN_PATH / "sign_config.json"

# 用户数据保存文件
PLAYER_PATH = MAIN_PATH / "players"

# 游戏素材
RESOURCE_PATH = MAIN_PATH / "resource"
AVATAR_PATH = RESOURCE_PATH / "avatar"  # 头像
WEAPON_PATH = RESOURCE_PATH / "weapon"  # 武器
PAINT_PATH = RESOURCE_PATH / "paint"  # 立绘
SKILL_PATH = RESOURCE_PATH / "skill"  # 技能
ATTR_PATH = RESOURCE_PATH / "attr"  # 属性
MOD_PATH = RESOURCE_PATH / "mod"  # mod
WEAPON_ATTR_PATH = RESOURCE_PATH / "weapon_attr"  # 武器属性
WEEKLY_ITEM_PATH = RESOURCE_PATH / "weekly_item"  # 周报资源图标
ID2NAME_PATH = RESOURCE_PATH / "id2name.json"  # id2name.json
# 别名
ALIAS_PATH = RESOURCE_PATH / "alias"
CHAR_ALIAS_PATH = ALIAS_PATH / "char_alias.json"  # char_alias.json
WEAPON_ALIAS_PATH = ALIAS_PATH / "weapon_alias.json"  # weapon_alias.json

# 自定义背景图
CUSTOM_PATH = MAIN_PATH / "custom"
CUSTOM_PAINT_PATH = CUSTOM_PATH / "custom_paint"  # 自定义立绘

# 其他的素材
OTHER_PATH = MAIN_PATH / "other"
SIGN_PATH = OTHER_PATH / "sign"
ANN_CARD_PATH = OTHER_PATH / "ann_card"
CALENDAR_PATH = OTHER_PATH / "calendar"


def init_dir():
    for i in [
        MAIN_PATH,
        SIGN_PATH,
        ANN_CARD_PATH,
        PLAYER_PATH,
        RESOURCE_PATH,
        AVATAR_PATH,
        WEAPON_PATH,
        PAINT_PATH,
        SKILL_PATH,
        ATTR_PATH,
        MOD_PATH,
        WEEKLY_ITEM_PATH,
        CUSTOM_PATH,
        CUSTOM_PAINT_PATH,
        ALIAS_PATH,
    ]:
        i.mkdir(parents=True, exist_ok=True)


init_dir()


# 设置 Jinja2 环境
TEMP_PATH = Path(__file__).parents[1].parent / "templates"
PLUGIN_LOGO_PATH = Path(__file__).parents[3] / "logo.png"
PLUGIN_LOGO_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(PLUGIN_LOGO_PATH.read_bytes()).decode("ascii")
)
TITLE_LOGO_PATH = (
    Path(__file__).parents[2] / "resources" / "textures" / "common" / "title_logo.png"
)
TITLE_LOGO_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(TITLE_LOGO_PATH.read_bytes()).decode("ascii")
    if TITLE_LOGO_PATH.exists()
    else PLUGIN_LOGO_DATA_URI
)
MUSIC_ON_PATH = (
    Path(__file__).parents[2] / "resources" / "textures" / "common" / "music_on.png"
)
MUSIC_ON_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(MUSIC_ON_PATH.read_bytes()).decode("ascii")
    if MUSIC_ON_PATH.exists()
    else ""
)
MUSIC_OFF_PATH = (
    Path(__file__).parents[2] / "resources" / "textures" / "common" / "music_off.png"
)
MUSIC_OFF_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(MUSIC_OFF_PATH.read_bytes()).decode("ascii")
    if MUSIC_OFF_PATH.exists()
    else ""
)
DNA_TEMPLATES = Environment(
    loader=FileSystemLoader(
        [
            str(TEMP_PATH),
        ]
    )
)
DNA_TEMPLATES.globals["plugin_logo"] = PLUGIN_LOGO_DATA_URI
DNA_TEMPLATES.globals["title_logo"] = TITLE_LOGO_DATA_URI
DNA_TEMPLATES.globals["music_on_icon"] = MUSIC_ON_DATA_URI
DNA_TEMPLATES.globals["music_off_icon"] = MUSIC_OFF_DATA_URI

