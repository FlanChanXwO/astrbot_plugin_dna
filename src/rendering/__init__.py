"""Rendering facade exposing infrastructure rendering components."""

from ..infrastructure.rendering import (
    AssetRenderError,
    RenderedArtifact,
    CheckinRenderer,
    ClipRect,
    EncyclopediaRenderer,
    HtmlRenderer,
    HtmlRenderError,
    HtmlRenderErrorKind,
    NoticesRenderer,
    PlayerRenderer,
    RenderedCheckinImage,
    RenderedEncyclopediaImage,
    RenderedNoticesImage,
    RenderedPlayerImage,
    RenderResultError,
    RenderSpec,
    ResourceMap,
    T2IRenderError,
    TemplateRenderError,
    build_profile_header,
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    render_qr_code,
    to_data_uri,
    unicode_font_data_uris,
)
from ..infrastructure.rendering import (
    assets as assets,
)
from ..infrastructure.rendering import (
    checkin as checkin,
)
from ..infrastructure.rendering import (
    encyclopedia as encyclopedia,
)
from ..infrastructure.rendering import (
    errors as errors,
)
from ..infrastructure.rendering import (
    fonts as fonts,
)
from ..infrastructure.rendering import (
    notices as notices,
)
from ..infrastructure.rendering import (
    payloads as payloads,
)
from ..infrastructure.rendering import (
    player as player,
)
from ..infrastructure.rendering import (
    qr as qr,
)
from ..infrastructure.rendering import (
    renderer as renderer,
)
from ..infrastructure.rendering import (
    spec as spec,
)

__all__ = [
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
    "RenderedArtifact",
    "RenderedCheckinImage",
    "RenderedEncyclopediaImage",
    "RenderedNoticesImage",
    "RenderedPlayerImage",
    "ResourceMap",
    "T2IRenderError",
    "TemplateRenderError",
    "assets",
    "build_profile_header",
    "checkin",
    "encyclopedia",
    "errors",
    "font_data_uri",
    "fonts",
    "image_data_uri",
    "notices",
    "optimized_image_data_uri",
    "payloads",
    "pil_image_data_uri",
    "player",
    "qr",
    "render_qr_code",
    "renderer",
    "spec",
    "to_data_uri",
    "unicode_font_data_uris",
]
