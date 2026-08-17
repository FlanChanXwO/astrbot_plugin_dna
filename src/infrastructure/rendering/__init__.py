"""玩家、签到、通知与资料图片渲染基础设施。"""

from dnaby.rendering import (
    AssetRenderError,
    HtmlRenderer,
    HtmlRenderError,
    RenderResultError,
    RenderSpec,
    T2IRenderError,
    TemplateRenderError,
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    to_data_uri,
    unicode_font_data_uris,
)

from .checkin import CheckinRenderer, RenderedCheckinImage
from .encyclopedia import EncyclopediaRenderer, RenderedEncyclopediaImage
from .notices import NoticesRenderer, RenderedNoticesImage
from .player import PlayerRenderer, RenderedPlayerImage, ResourceMap

__all__ = [
    "AssetRenderError",
    "CheckinRenderer",
    "EncyclopediaRenderer",
    "HtmlRenderError",
    "HtmlRenderer",
    "NoticesRenderer",
    "PlayerRenderer",
    "RenderResultError",
    "RenderSpec",
    "RenderedCheckinImage",
    "RenderedEncyclopediaImage",
    "RenderedNoticesImage",
    "RenderedPlayerImage",
    "ResourceMap",
    "T2IRenderError",
    "TemplateRenderError",
    "font_data_uri",
    "image_data_uri",
    "optimized_image_data_uri",
    "pil_image_data_uri",
    "to_data_uri",
    "unicode_font_data_uris",
]
