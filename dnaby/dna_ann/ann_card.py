from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

import httpx
from astrbot.api import logger
from PIL import Image, ImageOps

from ..dna_config import DNA_PREFIX
from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    unicode_font_data_uris,
)
from ..utils import dna_api
from ..utils.fonts.dna_fonts import UNICODE_ORIGIN_PATH
from ..utils.image_utils import convert_img
from ._image import (
    DETAIL_CACHE_PATH,
    PREVIEW_CACHE_PATH,
    cache_name,
    fetch_image,
    load_qr_code,
    round_avatar,
    shrink_to_width,
)
from .utils import (
    LIST_DISPLAY_LIMIT,
    extract_blocks,
    fetch_ann_list,
    format_post_time,
    get_post_url,
    pick_preview,
    pick_subject,
    pick_time,
    post_time_to_timestamp,
)

WIDTH = 1080
PADDING = 40
GRID_GAP = 24
PAGE_LIMIT = 6000
GRID_COLS = 3
BACKGROUND_PATH = Path(__file__).parents[1] / "utils" / "texture2d" / "bg.jpg"
_OFFICIAL_AVATAR = Path(__file__).parent / "texture2d" / "dna_official_avatar.jpeg"
_RENDERER = HtmlRenderer()


async def _load_preview(url: str, width: int, height: int) -> Image.Image | None:
    if not url:
        return None
    try:
        image = await fetch_image(PREVIEW_CACHE_PATH, url, name=cache_name("preview", url))
    except (OSError, httpx.HTTPError):
        return None
    return ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)


async def _load_detail_image(url: str, max_width: int) -> Image.Image:
    try:
        image = await fetch_image(DETAIL_CACHE_PATH, url, name=cache_name("detail", url))
    except (OSError, httpx.HTTPError):
        image = Image.new("RGB", (max_width, 200), "#2a2d3d")
    return shrink_to_width(image.convert("RGB"), max_width)




def _load_avatar(size: int) -> Image.Image:
    if _OFFICIAL_AVATAR.exists():
        return round_avatar(Image.open(_OFFICIAL_AVATAR).convert("RGBA"), size)
    return round_avatar(Image.new("RGB", (size, size), "#b22222"), size)


async def draw_ann_list_img(posts: list[dict] | None = None) -> bytes | str:
    """以 HTML/T2I 渲染公告索引卡，保留旧序号、条目上限和错误语义。"""

    if posts is None:
        posts = await fetch_ann_list(prefer_cache=True)
    if not posts:
        return "获取公告列表失败"

    visible = posts[:LIST_DISPLAY_LIMIT]
    rows = (len(visible) + GRID_COLS - 1) // GRID_COLS
    # 沿用 legacy PIL 的画布公式，避免浏览器根据字体和边框测量产生高度漂移。
    canvas_height = (
        168
        + 32
        + rows * 308
        + max(0, rows - 1) * GRID_GAP
        + 36
        + 96
        + PADDING
    )
    card_width = (WIDTH - PADDING * 2 - GRID_GAP * (GRID_COLS - 1)) // GRID_COLS
    image_height = 156
    cards: list[dict[str, str | int | None]] = []
    for idx, post in enumerate(visible, start=1):
        preview = await _load_preview(pick_preview(post), card_width, image_height)
        cards.append(
            {
                "index": idx,
                "preview": pil_image_data_uri(preview) if preview is not None else None,
                "subject": pick_subject(post),
                "time": pick_time(post),
            }
        )

    font, font_fallback = unicode_font_data_uris(
        UNICODE_ORIGIN_PATH,
        "".join(f"{card['subject']}{card['time'] or ''}" for card in cards),
    )
    return await _RENDERER.render(
        "cards/announcement_list.html.j2",
        {
            "background": optimized_image_data_uri(
                BACKGROUND_PATH,
                size=(WIDTH, canvas_height),
                crop=True,
                image_format="JPEG",
                quality=85,
            ),
            "cards": cards,
            "font": font,
            "font_fallback": font_fallback,
            "prefix": DNA_PREFIX,
            "width": WIDTH,
            "height": canvas_height,
        },
        RenderSpec(width=WIDTH, full_page=True, image_format="jpeg"),
    )


async def _detail_blocks_payload(blocks: list[tuple[str, str]]) -> list[dict[str, str]]:
    content_width = WIDTH - PADDING * 2
    payload: list[dict[str, str]] = []
    for kind, value in blocks:
        if kind == "text":
            payload.append({"kind": kind, "value": value})
        else:
            image = await _load_detail_image(value, content_width)
            payload.append({"kind": kind, "value": pil_image_data_uri(image)})
    return payload


async def _split_rendered_pages(rendered: bytes) -> bytes | list[bytes]:
    """仅裁剪 T2I 结果以保留公告多页消息语义，不重绘或截断内容。"""

    with Image.open(BytesIO(rendered)) as source:
        source.load()
        if source.height <= PAGE_LIMIT:
            return rendered
        pages: list[bytes] = []
        for top in range(0, source.height, PAGE_LIMIT):
            bottom = min(top + PAGE_LIMIT, source.height)
            pages.append(await convert_img(source.crop((0, top, source.width, bottom))))
    return pages


async def draw_ann_detail_card(
    post_id: int | str,
    subject: str,
    blocks: list[tuple[str, str]],
    *,
    time_text: str = "",
) -> bytes | list[bytes]:
    """使用 HTML/T2I 渲染已解析的公告正文卡片。"""

    post_id = str(post_id)
    qr_image = await load_qr_code(get_post_url(post_id))
    block_payload = await _detail_blocks_payload(blocks)
    font, font_fallback = unicode_font_data_uris(
        UNICODE_ORIGIN_PATH,
        f"{subject}{time_text}"
        + "".join(block["value"] for block in block_payload if block["kind"] == "text"),
    )
    rendered = await _RENDERER.render(
        "cards/announcement_detail.html.j2",
        {
            "avatar": pil_image_data_uri(_load_avatar(120)),
            "background": image_data_uri(BACKGROUND_PATH),
            "blocks": block_payload,
            "font": font,
            "font_fallback": font_fallback,
            "qr": pil_image_data_uri(qr_image) if qr_image is not None else None,
            "subject": subject,
            "time_text": time_text,
            "width": WIDTH,
        },
        RenderSpec(width=WIDTH, full_page=True, image_format="jpeg"),
    )
    return await _split_rendered_pages(rendered)


async def draw_ann_detail_img(
    post_id: int | str,
    *,
    is_check_time: bool = False,
) -> bytes | str | list[bytes]:
    post_id = str(post_id)
    posts = await fetch_ann_list(prefer_cache=True)
    matched = next((post for post in posts if str(post.get("postId")) == post_id), None)
    if matched is None:
        return "未找到该公告"

    response = await dna_api.get_post_detail(post_id)
    if not response.is_success or not isinstance(response.data, dict):
        return "未找到该公告"
    detail = response.data.get("postDetail") or {}
    if is_check_time:
        post_time = post_time_to_timestamp(detail.get("postTime"))
        now = int(time.time())
        logger.debug(f"[DNA公告] {post_id} post_time={post_time} now={now} delta={now - post_time}")
        if post_time and post_time < now - 86400:
            return "该公告已过期"

    blocks = extract_blocks(detail.get("postContent") or [])
    if not blocks:
        return "未找到该公告"

    subject = str(detail.get("postTitle") or pick_subject(matched))
    time_text = format_post_time(detail.get("postTime") or matched.get("postTime"))
    return await draw_ann_detail_card(post_id, subject, blocks, time_text=time_text)
