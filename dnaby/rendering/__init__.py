"""Jinja2 + AstrBot T2I 的统一图片渲染入口。"""

from .assets import (
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    to_data_uri,
    unicode_font_data_uris,
)
from .errors import (
    AssetRenderError,
    HtmlRenderError,
    HtmlRenderErrorKind,
    RenderResultError,
    T2IRenderError,
    TemplateRenderError,
)
from .payloads import build_profile_header
from .qr import render_qr_code
from .renderer import HtmlRenderer
from .spec import ClipRect, RenderSpec

__all__ = [
    "AssetRenderError",
    "ClipRect",
    "HtmlRenderError",
    "HtmlRenderErrorKind",
    "HtmlRenderer",
    "RenderResultError",
    "RenderSpec",
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
