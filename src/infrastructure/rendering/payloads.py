"""HTML 卡片共用的业务 payload 构建函数。"""

from __future__ import annotations

import httpx

from ...utils.image import get_avatar_img
from ...utils.image_utils import get_event_avatar
from ...utils.resource.RESOURCE_PATH import AVATAR_PATH
from ...utils.session import EventContext
from .assets import image_data_uri, pil_image_data_uri
from .legacy_assets import COMMON_PATH

TEXTURE_PATH = COMMON_PATH


async def build_profile_header(
    ctx: EventContext,
    role_id: str | int,
    name: str,
    *,
    user_level: int | None = None,
    stats: list[tuple[str, str]] | None = None,
    avatar_user_id: str | None = None,
    uid_hidden: bool = False,
) -> dict[str, object]:
    """保留原头像选择语义，返回可安全交给模板的资料头 payload。

    用户头像加载失败时继续沿用旧逻辑，使用游戏默认角色头像；这属于素材读取
    的既有回退，不会替代 HTML/T2I 渲染失败后的错误处理。
    """

    original_at = ctx.at
    ctx.at = avatar_user_id or ""
    try:
        avatar = await get_event_avatar(ctx, avatar_path=AVATAR_PATH)
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        avatar = await get_avatar_img("5101")
    finally:
        ctx.at = original_at

    return {
        "avatar": pil_image_data_uri(avatar),
        "avatar_frame": image_data_uri(TEXTURE_PATH / "avatar_frame.png"),
        "level": user_level,
        "level_background": image_data_uri(TEXTURE_PATH / "avatar_title_level.png"),
        "name": name,
        "stats": [{"label": label, "value": value} for label, value in stats or []],
        "stats_background": image_data_uri(TEXTURE_PATH / "avatar_title_base_info.png"),
        "uid": None if uid_hidden else str(role_id),
    }
