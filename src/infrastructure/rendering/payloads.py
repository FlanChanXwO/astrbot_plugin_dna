"""HTML 卡片共用的业务 payload 构建函数。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import httpx
from PIL import Image

from ...utils.image import get_avatar_img
from ...utils.image_utils import get_event_avatar
from ...utils.resource.RESOURCE_PATH import USER_AVATAR_PATH
from ...utils.session import EventContext
from .assets import pil_image_data_uri
from .static_assets import static_image_data_uri, static_record

if TYPE_CHECKING:
    from ..resources.resolver import AssetDownloader


class ProfileImageLoader(Protocol):
    """资料头所需的请求期用户头像加载边界。"""

    async def user_avatar(self, user_id: str) -> Image.Image:
        """使用当前 runtime 的图片下载器读取用户头像。"""


async def build_profile_header(
    ctx: EventContext,
    role_id: str | int,
    name: str,
    *,
    user_level: int | None = None,
    stats: list[tuple[str, str]] | None = None,
    avatar_user_id: str | None = None,
    uid_hidden: bool = False,
    downloader: AssetDownloader | None = None,
    avatar_path: Path | None = None,
    game_avatar_path: Path | None = None,
    image_loader: ProfileImageLoader | None = None,
    static_asset_resolver: object | None = None,
    static_records: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """保留原头像选择语义，返回可安全交给模板的资料头 payload。

    用户头像加载失败时继续沿用旧逻辑，使用游戏默认角色头像；这属于素材读取
    的既有回退，不会替代 HTML/T2I 渲染失败后的错误处理。
    静态装饰图经 StaticAssetResolver 从 verified snapshot 解析，缺失时降级。
    """

    if image_loader is not None:
        avatar = await image_loader.user_avatar(avatar_user_id or ctx.user_id)
    else:
        original_at = ctx.at
        ctx.at = avatar_user_id or ""
        try:
            avatar = await get_event_avatar(
                ctx,
                avatar_path=(USER_AVATAR_PATH if avatar_path is None else avatar_path),
                downloader=downloader,
            )
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            avatar = await get_avatar_img(
                "5101",
                avatar_path=game_avatar_path,
                downloader=downloader,
            )
        finally:
            ctx.at = original_at

    def image(key: str, relative: str) -> str:
        uri, asset = static_image_data_uri(
            static_asset_resolver, relative, label="资料头"
        )
        if static_records is not None:
            static_records.append(static_record(key, asset, resource_path=relative))
        return uri

    return {
        "avatar": pil_image_data_uri(avatar),
        "avatar_frame": image(
            "texture.common.avatar_frame", "textures/common/avatar_frame.png"
        ),
        "level": user_level,
        "level_background": image(
            "texture.common.avatar_title_level", "textures/common/avatar_title_level.png"
        ),
        "name": name,
        "stats": [{"label": label, "value": value} for label, value in stats or []],
        "stats_background": image(
            "texture.common.avatar_title_base_info",
            "textures/common/avatar_title_base_info.png",
        ),
        "uid": None if uid_hidden else str(role_id),
    }
