"""公告列表与详情解析工具。"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ...utils import dna_api
from .contracts import AnnDetail, AnnSnapshot

POST_DETAIL_URL_TPL = "https://dnabbs.yingxiong.com/pc/detail/{post_id}"

_HTML_BREAK_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_RELATIVE_TIME_PARTS = ("小时前", "分钟前", "刚刚")
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _parse_local_time(text: str, fmt: str) -> datetime:
    """将接口中的无时区文本按项目约定解释为上海时间。"""
    return datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI_TZ)


async def fetch_ann_list(*, prefer_cache: bool = True) -> list[dict[str, Any]]:
    # 保留参数以兼容 legacy 绘制入口；公告列表不再接受无 TTL 进程缓存。
    del prefer_cache
    return await dna_api.get_ann_list(is_cache=False) or []


def build_index_map(posts: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {idx: post for idx, post in enumerate(posts, start=1)}


def resolve_index(token: str, index_map: dict[int, dict[str, Any]]) -> str | None:
    cleaned = token.strip().replace("#", "")
    if not cleaned.isdigit():
        return None
    post = index_map.get(int(cleaned))
    return str(post["postId"]) if post else None


def get_post_url(post_id: str) -> str:
    return POST_DETAIL_URL_TPL.format(post_id=post_id)


def format_post_time(raw: Any) -> str:
    if raw in (None, ""):
        return ""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(int(raw), tz=SHANGHAI_TZ).strftime(
            "%Y-%m-%d %H:%M"
        )

    text = str(raw).strip()
    if any(part in text for part in _RELATIVE_TIME_PARTS):
        return text

    for fmt in _TIME_FORMATS:
        try:
            return _parse_local_time(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        year = datetime.now(tz=SHANGHAI_TZ).year
        return _parse_local_time(f"{year}-{text}", "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return text


def post_time_to_timestamp(raw: Any) -> int:
    if raw in (None, ""):
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)

    text = str(raw).strip()
    match = re.search(r"(\d+)\s*小时前", text)
    if match:
        return int(time.time()) - int(match.group(1)) * 3600
    match = re.search(r"(\d+)\s*分钟前", text)
    if match:
        return int(time.time()) - int(match.group(1)) * 60

    for fmt in _TIME_FORMATS:
        try:
            return int(_parse_local_time(text, fmt).timestamp())
        except ValueError:
            continue

    try:
        year = datetime.now(tz=SHANGHAI_TZ).year
        return int(_parse_local_time(f"{year}-{text}", "%Y-%m-%d").timestamp())
    except ValueError:
        return 0


def normalize_text(text: str) -> str:
    raw = html.unescape(text)
    raw = _HTML_BREAK_RE.sub("\n", raw)
    raw = _HTML_TAG_RE.sub("", raw)
    raw = raw.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    raw = _BLANK_LINE_RE.sub("\n\n", raw)
    return raw.strip()


def _is_image_url(value: object) -> bool:
    """接受 CDN 无扩展名 URL，同时拒绝本地路径和非 HTTP(S) 伪 URL。"""

    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def extract_blocks(post_content: list[dict[str, Any]]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for item in post_content or []:
        kind = item.get("contentType")
        if kind == 1:
            text = normalize_text(item.get("content") or "")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    blocks.append(("text", stripped))
        elif kind == 2:
            url = (item.get("url") or "").strip()
            if _is_image_url(url):
                blocks.append(("image", url))
        elif kind == 5:
            video = item.get("contentVideo") or {}
            cover = (video.get("coverUrl") or "").strip()
            if _is_image_url(cover):
                blocks.append(("image", cover))
    return blocks


def pick_preview(post: dict[str, Any]) -> str:
    cover = (post.get("postCover") or "").strip()
    if _is_image_url(cover):
        return cover
    video = post.get("videoContent") or {}
    if isinstance(video, dict):
        video_cover = (video.get("coverUrl") or "").strip()
        if _is_image_url(video_cover):
            return video_cover
    images = post.get("imgContent") or []
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, dict):
                url = (entry.get("url") or "").strip()
                if _is_image_url(url):
                    return url
    return ""


def pick_subject(post: dict[str, Any]) -> str:
    title = (post.get("postTitle") or "").strip()
    if title:
        return title
    content = post.get("postContent")
    if isinstance(content, str):
        text = normalize_text(content)
        if text:
            return text.splitlines()[0]
    return f"#{post.get('postId', '')}"


def pick_time(post: dict[str, Any]) -> str:
    show = (post.get("showTime") or "").strip()
    if show:
        return show
    raw = post.get("postTime") or post.get("createTime")
    return format_post_time(raw) if raw else ""


def announcement_fingerprint(value: AnnSnapshot | AnnDetail) -> str:
    """按完整公告内容生成稳定摘要，用于内容变化时提前切换缓存键。"""

    if isinstance(value, AnnSnapshot):
        payload: dict[str, object] = {
            "kind": "list",
            "posts": [
                {
                    "post_id": post.post_id,
                    "title": post.title,
                    "time": post.time,
                    "preview": post.preview,
                }
                for post in value.posts
            ],
        }
    elif isinstance(value, AnnDetail):
        payload = {
            "kind": "detail",
            "post_id": value.post_id,
            "title": value.title,
            "time": value.time,
            "blocks": [
                {
                    "kind": block.kind,
                    "text": block.text,
                    "image_url": block.image_url,
                }
                for block in value.blocks
            ],
        }
    else:
        raise TypeError("公告 fingerprint 只接受列表或详情快照")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
