"""将 T2I 所需的本地素材安全内联为 data URI。"""

from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

from .errors import AssetRenderError

AssetSource = bytes | bytearray | memoryview | Path

_MIME_BY_SUFFIX = {
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

_IMAGE_MIME_BY_FORMAT = {
    "AVIF": "image/avif",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def to_data_uri(source: AssetSource, *, media_type: str | None = None) -> str:
    """将本地路径或内存字节编码为 data URI。

    不接受 URL 或字符串路径，避免模板在 T2I 容器中依赖外部网络或本地路径。
    传入内存字节且无法推断 MIME 时，调用方必须显式指定 ``media_type``。
    """

    content, inferred_media_type = _read_asset(source)
    resolved_media_type = media_type or inferred_media_type
    if not resolved_media_type:
        raise AssetRenderError("无法推断素材 MIME 类型，请显式传入 media_type")
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{resolved_media_type};base64,{encoded}"


def image_data_uri(source: AssetSource, *, media_type: str | None = None) -> str:
    """内联图片素材；内存图片默认按 PNG 声明。"""

    if media_type is not None or isinstance(source, Path):
        return to_data_uri(source, media_type=media_type)
    return to_data_uri(source, media_type="image/png")


def font_data_uri(source: AssetSource, *, media_type: str | None = None) -> str:
    """内联字体素材；路径按扩展名推断，内存字体须显式给出 MIME。"""

    # 完整 TTF 仍保留给 PIL；浏览器侧优先使用同名 WOFF2，避免每次把大字体
    # 作为 base64 重复传给 T2I，同时不改变字形覆盖范围。
    if isinstance(source, Path) and source.suffix.lower() in {".ttf", ".otf"}:
        compressed = source.with_suffix(".woff2")
        if compressed.exists():
            source = compressed
    return to_data_uri(source, media_type=media_type)


def unicode_font_data_uris(source: Path, text: str) -> tuple[str, str | None]:
    """返回常用中文主字体，以及实际文本需要时才内联的完整 fallback。

    预构建字体把 Arial Unicode MS 拆成 GB2312/常用符号和剩余 glyph 两部分；
    两者 cmap 并集与原字体一致。这样不牺牲生僻字覆盖，也避免每张普通中文卡片
    都把完整 7 MiB WOFF2 传给 T2I。
    """

    primary = font_data_uri(source)
    if not any(_needs_unicode_fallback(char) for char in text):
        return primary, None

    fallback = source.with_name(f"{source.stem}-fallback.woff2")
    return primary, font_data_uri(fallback)


def _needs_unicode_fallback(char: str) -> bool:
    codepoint = ord(char)
    if (
        codepoint < 0x0250
        or 0x2000 <= codepoint < 0x27C0
        or 0x3000 <= codepoint < 0x3040
        or 0xFF00 <= codepoint < 0xFFF0
    ):
        return False
    try:
        char.encode("gb2312")
    except UnicodeEncodeError:
        # 原 Arial 字库的非 BMP 覆盖集中在 CJK 扩展区；现代 emoji 交给系统
        # emoji 字体，避免为原字库中不存在的字符误载 5 MiB fallback。
        return codepoint <= 0xFFFF or 0x20000 <= codepoint <= 0x2FA1F
    return False


def pil_image_data_uri(image: Image.Image, *, image_format: str = "PNG") -> str:
    """将经 PIL 裁剪、缩放或下载处理后的图片以内联 PNG/JPEG 等形式传给模板。"""

    format_name = image_format.upper()
    media_type = _IMAGE_MIME_BY_FORMAT.get(format_name)
    if not media_type:
        raise AssetRenderError(f"不支持的图片格式: {image_format}")

    try:
        buffer = BytesIO()
        image.save(buffer, format=format_name)
    except (OSError, ValueError) as exc:
        raise AssetRenderError("PIL 图片编码失败", cause=exc) from exc
    return to_data_uri(buffer.getvalue(), media_type=media_type)


def optimized_image_data_uri(
    source: Path,
    *,
    size: tuple[int, int],
    crop: bool = False,
    image_format: str = "WEBP",
    quality: int = 85,
) -> str:
    """按模板实际显示尺寸处理本地素材并缓存编码结果。

    ``crop=True`` 使用居中裁剪填满目标尺寸；否则保持比例缩略并透明留白。
    缓存键包含路径、mtime、文件大小和全部转换参数，素材更新后自然失效。
    """

    try:
        stat = source.stat()
    except OSError as exc:
        raise AssetRenderError(f"素材读取失败: {source}", cause=exc) from exc
    return _optimized_path_data_uri(
        str(source.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        size,
        crop,
        image_format.upper(),
        quality,
    )


@lru_cache(maxsize=512)
def _optimized_path_data_uri(
    path: str,
    mtime_ns: int,
    file_size: int,
    size: tuple[int, int],
    crop: bool,
    image_format: str,
    quality: int,
) -> str:
    del mtime_ns, file_size
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise AssetRenderError(f"图片素材读取失败: {path}", cause=exc) from exc

    if crop:
        source_ratio = image.width / image.height
        target_ratio = size[0] / size[1]
        if source_ratio > target_ratio:
            crop_width = round(image.height * target_ratio)
            left = (image.width - crop_width) // 2
            image = image.crop((left, 0, left + crop_width, image.height))
        else:
            crop_height = round(image.width / target_ratio)
            top = (image.height - crop_height) // 2
            image = image.crop((0, top, image.width, top + crop_height))
        image = image.resize(size, Image.Resampling.LANCZOS)
    else:
        image.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size)
        canvas.alpha_composite(
            image,
            ((size[0] - image.width) // 2, (size[1] - image.height) // 2),
        )
        image = canvas

    if image_format == "JPEG":
        image = image.convert("RGB")
    return _encode_pil_data_uri(image, image_format=image_format, quality=quality)


def _encode_pil_data_uri(image: Image.Image, *, image_format: str, quality: int) -> str:
    media_type = _IMAGE_MIME_BY_FORMAT.get(image_format)
    if not media_type:
        raise AssetRenderError(f"不支持的图片格式: {image_format}")
    try:
        buffer = BytesIO()
        kwargs = {"quality": quality} if image_format in ("JPEG", "WEBP") else {}
        image.save(buffer, format=image_format, **kwargs)
    except (OSError, ValueError) as exc:
        raise AssetRenderError("PIL 图片编码失败", cause=exc) from exc
    return to_data_uri(buffer.getvalue(), media_type=media_type)


def _read_asset(source: AssetSource) -> tuple[bytes, str | None]:
    if isinstance(source, Path):
        try:
            stat = source.stat()
            return _read_path_cached(
                str(source.resolve()), stat.st_mtime_ns, stat.st_size
            ), _guess_media_type(source)
        except OSError as exc:
            raise AssetRenderError(f"素材读取失败: {source}", cause=exc) from exc
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source), None
    raise AssetRenderError("素材必须为本地 Path 或已下载的 bytes，不能使用 URL")


@lru_cache(maxsize=512)
def _read_path_cached(path: str, mtime_ns: int, file_size: int) -> bytes:
    del mtime_ns, file_size
    return Path(path).read_bytes()


def _guess_media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(path.name)[0]
