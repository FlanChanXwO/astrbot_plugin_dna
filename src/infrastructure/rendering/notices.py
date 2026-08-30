"""密函与公告的 HTML/T2I 与确定性渲染器。"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus

import httpx
from astrbot.api import logger
from PIL import Image, ImageDraw, ImageOps
from PIL.PngImagePlugin import PngInfo

from ...modules.notices.ann_utils import (
    announcement_fingerprint,
    extract_blocks,
    fetch_ann_list,
    format_post_time,
    get_post_url,
    pick_preview,
    pick_subject,
    pick_time,
    post_time_to_timestamp,
)
from ...modules.notices.contracts import AnnDetail, AnnSnapshot, MhSnapshot
from ...utils import dna_api, get_datetime
from ...utils.api.mh_map import get_mh_type_name
from ...utils.api.model import DNARoleForToolInstanceInfo
from ...utils.image_utils import convert_img, download
from ...utils.resource.RESOURCE_PATH import ANN_CARD_PATH
from ..resources.encyclopedia import EncyclopediaResourceStore
from .assets import (
    font_data_uri,
    image_data_uri,
    optimized_image_data_uri,
    pil_image_data_uri,
    unicode_font_data_uris,
)
from .renderer import HtmlRenderer
from .spec import RenderSpec

if TYPE_CHECKING:
    from ...infrastructure.cache import CacheManager

_RENDERER = HtmlRenderer()
RESOURCES_DIR = Path(__file__).parents[2] / "resources"
MH_TEXT_PATH = RESOURCES_DIR / "textures" / "mh"
ANN_TEXT_PATH = RESOURCES_DIR / "textures" / "ann"
COMMON_PATH = RESOURCES_DIR / "textures" / "common"
FONT_ORIGIN_PATH = RESOURCES_DIR / "fonts" / "dna_fonts.ttf"
UNICODE_ORIGIN_PATH = RESOURCES_DIR / "fonts" / "arial-unicode-ms-bold.ttf"
_OFFICIAL_AVATAR = ANN_TEXT_PATH / "dna_official_avatar.jpeg"

QR_CACHE_PATH = ANN_CARD_PATH / "qr"
PREVIEW_CACHE_PATH = ANN_CARD_PATH / "preview"
DETAIL_CACHE_PATH = ANN_CARD_PATH / "detail"

ANN_WIDTH = 1080
ANN_PADDING = 40
ANN_GRID_GAP = 24
ANN_PAGE_LIMIT = 6000
PAGE_LIMIT = ANN_PAGE_LIMIT
ANN_GRID_COLS = 3
MH_BG_LIST = ["bg1.jpg", "bg2.jpg", "bg3.jpg"]


def _image_validator(content: bytes) -> bool:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (OSError, SyntaxError, ValueError):
        return False
    return True


_png_validator = _image_validator


def _json_object_validator(content: bytes) -> bool:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict)


def _cache_name(*parts: object, ext: str = "png") -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.{ext}"


async def _fetch_image(path: Path, pic_url: str, *, name: str | None = None) -> Image.Image:
    path.mkdir(parents=True, exist_ok=True)
    file_name = name or pic_url.split("/")[-1]
    target = path / file_name
    await download(pic_url, path, file_name, tag="[DNA]")
    return Image.open(target).convert("RGBA")


async def _fetch_image_bytes(pic_url: str) -> bytes:
    """下载并校验一张临时源图，成功后由调用方决定是否进入统一缓存。"""

    with tempfile.TemporaryDirectory(prefix="dnaby-ann-source-") as directory:
        target_dir = Path(directory)
        file_name = _cache_name("source", pic_url, ext="image")
        target = await download(pic_url, target_dir, file_name, tag="[DNA]")
        return target.read_bytes()


def _image_from_bytes(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content)) as image:
        image.load()
        return image.convert("RGBA")


async def _source_image_content(
    url: str,
    *,
    cache_manager: CacheManager | None,
    kind: str,
) -> bytes:
    if cache_manager is None:
        return await _fetch_image_bytes(url)
    key = f"ann-source:{kind}:{url}"
    lookup = await cache_manager.get(
        "announcement",
        key,
        validator=_image_validator,
    )
    if lookup.entry is not None:
        return lookup.entry.content
    content = await _fetch_image_bytes(url)
    await cache_manager.put(
        "announcement",
        key,
        content,
        tags=("announcement", "source", kind),
        validator=_image_validator,
    )
    return content


async def _load_qr_code(url: str, size: int = 220) -> Image.Image | None:
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={quote_plus(url)}"
    try:
        image = await _fetch_image(QR_CACHE_PATH, qr_url, name=_cache_name("qr", url, size))
    except (OSError, httpx.HTTPError):
        return None
    return image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)


load_qr_code = _load_qr_code


def _shrink_to_width(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image
    ratio = max_width / image.width
    return image.resize((int(max_width), int(image.height * ratio)), Image.Resampling.LANCZOS)


def _round_avatar(image: Image.Image, size: int) -> Image.Image:
    resized = image.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(resized, (0, 0), mask)
    return output


def _load_avatar(size: int) -> Image.Image:
    if _OFFICIAL_AVATAR.exists():
        return _round_avatar(Image.open(_OFFICIAL_AVATAR).convert("RGBA"), size)
    return _round_avatar(Image.new("RGB", (size, size), "#b22222"), size)


async def _load_preview(
    url: str,
    width: int,
    height: int,
    *,
    strict: bool = False,
    cache_manager: CacheManager | None = None,
) -> Image.Image | None:
    if not url:
        return None
    try:
        if cache_manager is None:
            image = await _fetch_image(
                PREVIEW_CACHE_PATH,
                url,
                name=_cache_name("preview", url),
            )
        else:
            image = _image_from_bytes(
                await _source_image_content(
                    url,
                    cache_manager=cache_manager,
                    kind="preview",
                ),
            )
    except (OSError, httpx.HTTPError):
        if strict:
            raise
        return None
    return ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)


async def _load_detail_image(
    url: str,
    max_width: int,
    *,
    cache_manager: CacheManager | None = None,
) -> Image.Image:
    if cache_manager is None:
        image = await _fetch_image(
            DETAIL_CACHE_PATH,
            url,
            name=_cache_name("detail", url),
        )
    else:
        image = _image_from_bytes(
            await _source_image_content(
                url,
                cache_manager=cache_manager,
                kind="detail",
            ),
        )
    return _shrink_to_width(image.convert("RGB"), max_width)


def _is_subscribed(instance_name: str, type_name: str, subscribe_list: list[str] | None) -> bool:
    return bool(subscribe_list and (instance_name in subscribe_list or f"{type_name}:{instance_name}" in subscribe_list))


def _mh_payload(
    mh_result: list[DNARoleForToolInstanceInfo],
    subscribe_list: list[str] | None,
) -> list[dict[str, object]]:
    """将密函数据和本地类型图标转换为 HTML 模板 payload。"""

    entries: list[dict[str, object]] = []
    for mh in mh_result:
        if not mh.mh_type:
            logger.warning("mh_type is None: %s", mh.model_json_schema())
            continue
        type_name = get_mh_type_name(mh.mh_type)
        icon_path = MH_TEXT_PATH / f"mh_{mh.mh_type}.png"
        entries.append(
            {
                "icon": image_data_uri(icon_path) if icon_path.exists() else None,
                "instances": [
                    {
                        "name": instance.name,
                        "subscribed": _is_subscribed(instance.name, type_name, subscribe_list),
                    }
                    for instance in mh.instances
                ],
                "type_name": type_name,
            }
        )
    return entries


def format_seconds(seconds: int) -> str:
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}分钟{seconds}秒"


def _simple_refresh_text(seconds: int) -> str:
    """恢复旧简图 footer 的轮换时段和倒计时文本。"""

    now = get_datetime()
    return f"{now.hour}:00 - {(now.hour + 1) % 24}:00   {format_seconds(seconds)}后刷新"


async def draw_mh_simple(
    mh_result: list[DNARoleForToolInstanceInfo],
    remaining_seconds: int,
    subscribe_list: list[str] | None = None,
) -> bytes:
    """渲染固定高度的简洁密函图，保留旧动态列宽公式。"""

    card_width, gutter = 320, 20
    entries = _mh_payload(mh_result, subscribe_list)
    width = (card_width + gutter) * len(mh_result) + gutter
    return await _RENDERER.render(
        "cards/mh_simple.html.j2",
        {
            "entries": entries,
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "refresh_text": _simple_refresh_text(remaining_seconds),
            "width": width,
        },
        RenderSpec(width=width, height=646, full_page=True),
    )


async def draw_mh_card(
    mh_result: list[DNARoleForToolInstanceInfo],
    remaining_seconds: int,
    subscribe_list: list[str] | None = None,
    bg_name: str | None = None,
) -> bytes:
    """渲染旧 1700×900 密函卡片，随机背景仍由业务层选择。"""

    bg_path = MH_TEXT_PATH / (bg_name or random.choice(MH_BG_LIST))
    if not bg_path.exists():
        bg_path = COMMON_PATH / "bg1.jpg"

    return await _RENDERER.render(
        "cards/mh_card.html.j2",
        {
            "background": image_data_uri(bg_path),
            "bar": image_data_uri(MH_TEXT_PATH / "bar.png"),
            "cards": _mh_payload(mh_result, subscribe_list),
            "card_background": image_data_uri(MH_TEXT_PATH / "card.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer": image_data_uri(COMMON_PATH / "footer.png"),
            "height": 900,
            "refresh_text": f"{format_seconds(remaining_seconds)}后刷新",
            "refresh_background": image_data_uri(MH_TEXT_PATH / "refresh_time.png"),
            "title": image_data_uri(MH_TEXT_PATH / "title.png"),
            "width": 1700,
        },
        RenderSpec(width=1700, height=900, full_page=True, output_format="jpeg"),
    )


async def draw_ann_list_img(
    posts: list[dict] | None = None,
    *,
    strict_previews: bool = False,
    cache_manager: CacheManager | None = None,
) -> bytes | str:
    """以 HTML/T2I 渲染包含全部公告的索引卡。"""

    if posts is None:
        posts = await fetch_ann_list(prefer_cache=True)
    if not posts:
        return "获取公告列表失败"

    rows = (len(posts) + ANN_GRID_COLS - 1) // ANN_GRID_COLS
    canvas_height = (
        168
        + 32
        + rows * 308
        + max(0, rows - 1) * ANN_GRID_GAP
        + 36
        + 96
        + ANN_PADDING
    )
    card_width = (ANN_WIDTH - ANN_PADDING * 2 - ANN_GRID_GAP * (ANN_GRID_COLS - 1)) // ANN_GRID_COLS
    image_height = 156
    cards: list[dict[str, str | int | None]] = []
    for idx, post in enumerate(posts, start=1):
        try:
            preview_url = pick_preview(post)
            if strict_previews or cache_manager is not None:
                preview = await _load_preview(
                    preview_url,
                    card_width,
                    image_height,
                    strict=strict_previews,
                    cache_manager=cache_manager,
                )
            else:
                preview = await _load_preview(
                    preview_url,
                    card_width,
                    image_height,
                )
        except (OSError, httpx.HTTPError):
            if strict_previews:
                raise
            preview = None
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
                COMMON_PATH / "bg.jpg",
                size=(ANN_WIDTH, canvas_height),
                crop=True,
                image_format="JPEG",
                quality=85,
            ),
            "cards": cards,
            "font": font,
            "font_fallback": font_fallback,
            "prefix": "dna",
            "width": ANN_WIDTH,
            "height": canvas_height,
        },
        RenderSpec(width=ANN_WIDTH, full_page=True, output_format="jpeg"),
    )


async def _detail_blocks_payload(
    blocks: list[tuple[str, str]],
    *,
    cache_manager: CacheManager | None = None,
) -> list[dict[str, str]]:
    content_width = ANN_WIDTH - ANN_PADDING * 2
    payload: list[dict[str, str]] = []
    for kind, value in blocks:
        if kind == "text":
            payload.append({"kind": kind, "value": value})
        else:
            if cache_manager is None:
                image = await _load_detail_image(value, content_width)
            else:
                image = await _load_detail_image(
                    value,
                    content_width,
                    cache_manager=cache_manager,
                )
            payload.append({"kind": kind, "value": pil_image_data_uri(image)})
    return payload


async def _split_rendered_pages(rendered: bytes) -> bytes | list[bytes]:
    """仅裁剪 T2I 结果以保留公告多页消息语义，不重绘或截断内容。"""

    with Image.open(BytesIO(rendered)) as source:
        source.load()
        if source.height <= ANN_PAGE_LIMIT:
            return rendered
        pages: list[bytes] = []
        for top in range(0, source.height, ANN_PAGE_LIMIT):
            bottom = min(top + ANN_PAGE_LIMIT, source.height)
            pages.append(await convert_img(source.crop((0, top, source.width, bottom))))
    return pages


async def draw_ann_detail_card(
    post_id: int | str,
    subject: str,
    blocks: list[tuple[str, str]],
    *,
    time_text: str = "",
    cache_manager: CacheManager | None = None,
) -> bytes | list[bytes]:
    """使用 HTML/T2I 渲染已解析的公告正文卡片。"""

    post_id = str(post_id)
    qr_image = await globals()["load_qr_code"](get_post_url(post_id))
    block_payload = await _detail_blocks_payload(
        blocks,
        cache_manager=cache_manager,
    )
    font, font_fallback = unicode_font_data_uris(
        UNICODE_ORIGIN_PATH,
        f"{subject}{time_text}"
        + "".join(block["value"] for block in block_payload if block["kind"] == "text"),
    )
    rendered = await _RENDERER.render(
        "cards/announcement_detail.html.j2",
        {
            "avatar": pil_image_data_uri(_load_avatar(120)),
            "background": image_data_uri(COMMON_PATH / "bg.jpg"),
            "blocks": block_payload,
            "font": font,
            "font_fallback": font_fallback,
            "qr": pil_image_data_uri(qr_image) if qr_image is not None else None,
            "subject": subject,
            "time_text": time_text,
            "width": ANN_WIDTH,
        },
        RenderSpec(width=ANN_WIDTH, full_page=True, output_format="jpeg"),
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


@dataclass(frozen=True, slots=True)
class RenderedNoticesImage:
    """渲染结果及可审查的非框架元数据。"""

    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]


class NoticesRenderer:
    """生成密函与公告卡片的运行期 PNG。"""

    def __init__(
        self,
        output_dir: str | Path,
        resources: EncyclopediaResourceStore,
        *,
        simple_image: bool = False,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources
        self.simple_image = simple_image
        self.cache_manager = cache_manager

    @staticmethod
    def list_cache_key(snapshot: AnnSnapshot) -> str:
        return f"ann-list:{announcement_fingerprint(snapshot)}"

    @staticmethod
    def detail_manifest_key(detail: AnnDetail) -> str:
        return f"ann-detail-manifest:{detail.post_id}:{announcement_fingerprint(detail)}"

    @staticmethod
    def detail_cache_key(detail: AnnDetail, *, page_index: int) -> str:
        if page_index < 0:
            raise ValueError("公告详情页序号不能为负数")
        return (
            f"ann-detail-page:{detail.post_id}:"
            f"{announcement_fingerprint(detail)}:{page_index}"
        )

    async def _cached_png(self, key: str) -> bytes | None:
        if self.cache_manager is None:
            return None
        lookup = await self.cache_manager.get(
            "announcement",
            key,
            validator=_png_validator,
        )
        if lookup.entry is None:
            return None
        return lookup.entry.content

    async def _store_png(self, key: str, content: bytes, *, tags: tuple[str, ...]) -> None:
        if self.cache_manager is None:
            return
        await self.cache_manager.put(
            "announcement",
            key,
            content,
            tags=tags,
            validator=_png_validator,
        )

    def _write_cached(
        self,
        content: bytes,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
    ) -> RenderedNoticesImage:
        with Image.open(BytesIO(content)) as source:
            source.load()
            image = source.convert("RGBA")
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def _cached_detail_pages(self, detail: AnnDetail) -> list[bytes] | None:
        if self.cache_manager is None:
            return None
        manifest = await self.cache_manager.get(
            "announcement",
            self.detail_manifest_key(detail),
            validator=_json_object_validator,
        )
        if manifest.entry is None:
            return None
        try:
            raw = json.loads(manifest.entry.content.decode("utf-8"))
            page_indexes = raw["pages"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(page_indexes, list)
            or not page_indexes
            or any(type(index) is not int or index < 0 for index in page_indexes)
        ):
            return None
        pages: list[bytes] = []
        for page_index in page_indexes:
            page = await self._cached_png(
                self.detail_cache_key(detail, page_index=page_index),
            )
            if page is None:
                return None
            pages.append(page)
        return pages

    def _font_resource(self) -> dict[str, str]:
        return {
            "kind": "font",
            "key": "dna_fonts",
            "status": self.resources.font_status,
            "source": "fonts/dna_fonts.ttf" if self.resources.font_path is not None else "",
        }

    def _write(
        self,
        image: Image.Image,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
    ) -> RenderedNoticesImage:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"notices-{uuid.uuid4().hex}.png"
        metadata = PngInfo()
        metadata.add_text("dnaby.text", "\n".join(lines))
        metadata.add_text(
            "dnaby.layout",
            json.dumps(
                {"width": image.width, "height": image.height, "sections": sections},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        metadata.add_text(
            "dnaby.resources",
            json.dumps(resources, ensure_ascii=False, separators=(",", ":")),
        )
        image.convert("RGBA").save(path, format="PNG", pnginfo=metadata)
        return RenderedNoticesImage(
            path=path,
            width=image.width,
            height=image.height,
            text_lines=tuple(lines),
            resources=tuple(resources),
            sections=tuple(sections),
        )

    async def render_mh(
        self,
        snapshot: MhSnapshot,
        *,
        simple_image: bool | None = None,
        subscribe_list: list[str] | None = None,
    ) -> RenderedNoticesImage:
        """根据配置或入参渲染标准 1700×900 密函大图卡片或简洁分栏卡。"""

        is_simple = self.simple_image if simple_image is None else simple_image
        legacy = [
            DNARoleForToolInstanceInfo.model_validate(
                {
                    "mh_type": section.mh_type,
                    "instances": [
                        {"id": item.instance_id, "name": item.name}
                        for item in section.instances
                    ],
                },
            )
            for section in snapshot.sections
        ]
        now = get_datetime()
        next_refresh = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        remaining_seconds = int((next_refresh - now).total_seconds())
        if is_simple:
            image_bytes = await draw_mh_simple(
                legacy,
                remaining_seconds,
                subscribe_list=subscribe_list,
            )
        else:
            image_bytes = await draw_mh_card(
                legacy,
                remaining_seconds,
                subscribe_list=subscribe_list,
            )
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGBA")

        lines = ["二重螺旋 · 密函"]
        for section in snapshot.sections:
            lines.append(f"{section.type_name}:")
            lines.extend(f"{item.name} (id={item.instance_id})" for item in section.instances)
        resources: list[dict[str, str]] = [self._font_resource()]
        sections: list[dict[str, Any]] = []
        for section in snapshot.sections:
            sections.append(
                {
                    "name": section.type_name,
                    "items": len(section.instances),
                },
            )
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def render_ann_list(self, snapshot: AnnSnapshot) -> RenderedNoticesImage:
        """渲染公告列表，按序号展示全部公告标题与时间。"""

        lines = ["二重螺旋 · 公告列表"]
        resources: list[dict[str, str]] = [self._font_resource()]
        for index, post in enumerate(snapshot.posts, start=1):
            lines.append(f"{index}. {post.title}")
            if post.time:
                lines.append(f"   {post.time}")
            resources.append(
                {
                    "kind": "ann_preview",
                    "key": post.post_id,
                    "source": post.preview,
                    "status": "provided" if post.preview else "placeholder",
                },
            )
        sections: list[dict[str, Any]] = [{"name": "公告", "items": len(snapshot.posts)}]
        cache_key = self.list_cache_key(snapshot)
        cached = await self._cached_png(cache_key)
        if cached is not None:
            return self._write_cached(
                cached,
                lines=lines,
                resources=resources,
                sections=sections,
            )

        payload = [
            {"postId": post.post_id, "postTitle": post.title, "postTime": post.time, "postCover": post.preview}
            for post in snapshot.posts
        ]
        if self.cache_manager is None:
            image_bytes = await draw_ann_list_img(payload, strict_previews=True)
        else:
            image_bytes = await draw_ann_list_img(
                payload,
                strict_previews=True,
                cache_manager=self.cache_manager,
            )
        if not isinstance(image_bytes, bytes):
            raise TypeError("公告列表 legacy 绘制失败")
        rendered = self._write_cached(
            image_bytes,
            lines=lines,
            resources=resources,
            sections=sections,
        )
        await self._store_png(
            cache_key,
            rendered.path.read_bytes(),
            tags=("announcement", "list", f"fingerprint:{announcement_fingerprint(snapshot)}"),
        )
        return rendered

    async def render_ann_detail(self, detail: AnnDetail) -> RenderedNoticesImage | tuple[RenderedNoticesImage, ...]:
        """复用 legacy 公告详情布局，保留中文字体、正文图片与分页。"""

        lines = ["二重螺旋 · 公告详情", detail.title]
        resources: list[dict[str, str]] = [self._font_resource()]
        text_lines: list[str] = []
        blocks: list[tuple[str, str]] = []
        for index, block in enumerate(detail.blocks):
            if block.kind == "text":
                text_lines.append(block.text)
                blocks.append(("text", block.text))
                continue
            resources.append(
                {
                    "kind": "ann_image",
                    "key": f"{detail.post_id}-{index}",
                    "source": block.image_url,
                    "status": "provided",
                },
            )
            text_lines.append("[图片]")
            blocks.append(("image", block.image_url))

        lines.extend(text_lines)
        sections: list[dict[str, Any]] = [{"name": "详情正文", "items": len(detail.blocks)}]
        fingerprint = announcement_fingerprint(detail)
        cached_pages = await self._cached_detail_pages(detail)
        if cached_pages is not None:
            rendered_pages = [
                self._write_cached(
                    page,
                    lines=lines,
                    resources=resources,
                    sections=sections,
                )
                for page in cached_pages
            ]
        else:
            if self.cache_manager is None:
                raw_result = await draw_ann_detail_card(
                    detail.post_id,
                    detail.title,
                    blocks,
                    time_text=getattr(detail, "time", ""),
                )
            else:
                raw_result = await draw_ann_detail_card(
                    detail.post_id,
                    detail.title,
                    blocks,
                    time_text=getattr(detail, "time", ""),
                    cache_manager=self.cache_manager,
                )
            raw_pages = raw_result if isinstance(raw_result, list) else [raw_result]
            if not raw_pages:
                raise ValueError("公告详情渲染没有生成图片")
            rendered_pages = [
                self._write_cached(
                    page,
                    lines=lines,
                    resources=resources,
                    sections=sections,
                )
                for page in raw_pages
            ]
            if self.cache_manager is not None:
                for page_index, rendered in enumerate(rendered_pages):
                    await self._store_png(
                        self.detail_cache_key(detail, page_index=page_index),
                        rendered.path.read_bytes(),
                        tags=("announcement", "detail", f"fingerprint:{fingerprint}"),
                    )
                manifest = json.dumps(
                    {"pages": list(range(len(rendered_pages)))},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                await self.cache_manager.put(
                    "announcement",
                    self.detail_manifest_key(detail),
                    manifest,
                    tags=("announcement", "detail", f"fingerprint:{fingerprint}"),
                    validator=_json_object_validator,
                )
        if len(rendered_pages) == 1:
            return rendered_pages[0]
        return tuple(rendered_pages)


__all__ = [
    "NoticesRenderer",
    "RenderedNoticesImage",
    "_is_subscribed",
    "_mh_payload",
    "draw_ann_detail_card",
    "draw_ann_detail_img",
    "draw_ann_list_img",
    "draw_mh_card",
    "draw_mh_simple",
    "format_seconds",
]
