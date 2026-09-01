"""玩家、签到、通知与资料图片渲染基础设施。"""

from .artifact import RenderedArtifact
from .artifact_store import (
    artifact_validator,
    read_rendered_artifact,
    write_rendered_artifact,
)
from .assets import (
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    to_data_uri,
    unicode_font_data_uris,
)
from .checkin import CheckinRenderer, RenderedCheckinImage
from .encyclopedia import EncyclopediaRenderer, RenderedEncyclopediaImage
from .errors import (
    AssetRenderError,
    HtmlRenderError,
    HtmlRenderErrorKind,
    RenderResultError,
    T2IRenderError,
    TemplateRenderError,
)
from .notices import NoticesRenderer, RenderedNoticesImage
from .payloads import build_profile_header
from .player import PlayerRenderer, RenderedPlayerImage, ResourceMap
from .qr import render_qr_code
from .renderer import HtmlRenderer
from .spec import ClipRect, RenderSpec
from .temporary import (
    DEFAULT_RENDERED_PREFIXES,
    RenderedCleanupReport,
    RenderedFileStore,
)

__all__ = [
    "DEFAULT_RENDERED_PREFIXES",
    "AssetRenderError",
    "CheckinRenderer",
    "ClipRect",
    "EncyclopediaRenderer",
    "HtmlRenderError",
    "HtmlRenderErrorKind",
    "HtmlRenderer",
    "NoticesRenderer",
    "PlayerRenderer",
    "RenderResultError",
    "RenderSpec",
    "RenderedCheckinImage",
    "RenderedCleanupReport",
    "RenderedEncyclopediaImage",
    "RenderedFileStore",
    "RenderedNoticesImage",
    "RenderedPlayerImage",
    "ResourceMap",
    "RenderedArtifact",
    "artifact_validator",
    "read_rendered_artifact",
    "write_rendered_artifact",
    "T2IRenderError",
    "TemplateRenderError",
    "build_profile_header",
    "font_data_uri",
    "image_data_uri",
    "optimized_image_data_uri",
    "pil_image_data_uri",
    "render_qr_code",
    "to_data_uri",
    "unicode_font_data_uris",
]
