"""运行期资源路径兼容投影。

路径由 :class:`RuntimeDataLayout` 统一计算；本模块只定义路径和模板对象，
不在导入时创建运行期目录或文件。公共资源与动态缓存的最终分层由基础设施
资源流水线负责，本模块只保留现有调用方仍使用的兼容投影。
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ...infrastructure.data_layout import RuntimeDataLayout


def _default_data_dir() -> Path:
    """解析测试或 AstrBot 提供的插件运行期数据根。"""

    if data_dir := os.environ.get("DNABY_DATA_DIR"):
        return Path(data_dir)

    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    return Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_dna"


RUNTIME_DATA_LAYOUT = RuntimeDataLayout.from_data_dir(_default_data_dir())
MAIN_PATH = RUNTIME_DATA_LAYOUT.data_dir

# 动态游戏素材统一写入 cache/assets；游戏头像和事件用户头像分开保存。
RESOURCE_PATH = RUNTIME_DATA_LAYOUT.cache_assets_dir
AVATAR_PATH = RUNTIME_DATA_LAYOUT.cache_game_avatar_dir  # 游戏角色头像
USER_AVATAR_PATH = RUNTIME_DATA_LAYOUT.cache_user_avatar_dir  # 事件用户头像
WEAPON_PATH = RESOURCE_PATH / "weapon"  # 武器
PAINT_PATH = RESOURCE_PATH / "paint"  # 立绘
SKILL_PATH = RESOURCE_PATH / "skill"  # 技能
ATTR_PATH = RESOURCE_PATH / "attr"  # 属性
MOD_PATH = RESOURCE_PATH / "mod"  # mod
WEAPON_ATTR_PATH = RESOURCE_PATH / "weapon_attr"  # 武器属性
WEEKLY_ITEM_PATH = RESOURCE_PATH / "weekly_item"  # 周报资源图标

# 运行期别名统一放在 state/aliases，角色和武器文件名是稳定契约。
ALIAS_PATH = RUNTIME_DATA_LAYOUT.aliases_dir
CHAR_ALIAS_PATH = RUNTIME_DATA_LAYOUT.char_alias_path
WEAPON_ALIAS_PATH = RUNTIME_DATA_LAYOUT.weapon_alias_path

# 其他媒体缓存统一写入 cache/media。
OTHER_PATH = RUNTIME_DATA_LAYOUT.cache_media_dir
SIGN_PATH = RUNTIME_DATA_LAYOUT.cache_sign_dir
ANN_CARD_PATH = RUNTIME_DATA_LAYOUT.cache_ann_card_dir
CALENDAR_PATH = RUNTIME_DATA_LAYOUT.cache_calendar_dir
LOGIN_QR_PATH = RUNTIME_DATA_LAYOUT.cache_login_qr_dir

# 设置 Jinja2 环境
TEMP_PATH = Path(__file__).parents[1].parent / "templates"
PLUGIN_LOGO_PATH = Path(__file__).parents[3] / "logo.png"
PLUGIN_LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(
    PLUGIN_LOGO_PATH.read_bytes()
).decode("ascii")
TITLE_LOGO_PATH = (
    Path(__file__).parents[2] / "resources" / "textures" / "common" / "title_logo.png"
)
TITLE_LOGO_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(TITLE_LOGO_PATH.read_bytes()).decode("ascii")
    if TITLE_LOGO_PATH.exists()
    else PLUGIN_LOGO_DATA_URI
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
