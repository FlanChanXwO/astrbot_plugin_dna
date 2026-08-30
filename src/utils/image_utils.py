"""原生图片工具：替代 gsucore ``image_tools`` / ``download_file`` / ``qrlogin``。

- ``convert_img``：PIL/路径 → PNG bytes
- ``crop_center_img`` / ``tint_image``：纯 PIL 实现
- ``ImageFetcher`` / ``download``：带重试、校验和原子替换的运行期图片下载
- ``get_event_avatar``：按用户 id 拉头像（QQ 头像源），失败抛异常由调用方兜底
- ``change_ev_image_to_bytes``：URL/路径/bytes → bytes（上传用）
- ``get_qrcode_base64``：兼容入口，URL → HTML/T2I 二维码 PNG bytes
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import httpx
from astrbot.api import logger
from PIL import Image

from .session import EventContext

__all__ = [
    "ImageFetchError",
    "ImageFetcher",
    "change_ev_image_to_bytes",
    "convert_img",
    "crop_center_img",
    "download",
    "get_event_avatar",
    "get_qrcode_base64",
    "tint_image",
]


async def convert_img(
    img: bytes | str | Path | Image.Image,
    background: str | None = None,
) -> bytes:
    """PIL 图片 / 图片路径 / bytes → PNG bytes。"""
    if isinstance(img, bytes):
        return img
    if isinstance(img, (str, Path)):
        im = Image.open(img)
    else:
        im = img
    im = im.convert("RGBA" if background is None else "RGB")
    if background is not None:
        bg = Image.new("RGB", im.size, background)
        bg.paste(im, mask=im.split()[-1])
        im = bg
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def crop_center_img(img: Image.Image, w: int, h: int) -> Image.Image:
    """中心裁剪并缩放至 (w, h)。"""
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        return img
    ratio = max(w / img.width, h / img.height)
    new_w, new_h = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def tint_image(img: Image.Image, color: tuple) -> Image.Image:
    """将图片整体染成指定颜色（保留 alpha）。"""
    img = img.convert("RGBA")
    alpha = img.split()[-1]
    tinted = Image.new("RGBA", img.size, color)
    out = Image.composite(tinted, img, alpha)
    out.putalpha(alpha)
    return out


class ImageFetchError(OSError):
    """图片下载、缓存校验或原子写入失败。"""


def _validate_image_file(path: Path) -> None:
    """完整解码图片，避免把 HTML、空响应或损坏文件当作缓存成功。"""

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ImageFetchError(f"图片不可解码: {path.name}") from exc


def _retry_after_seconds(headers: Any) -> float | None:
    """解析 Retry-After 的秒数或 HTTP 日期；无效值交给指数退避。"""

    raw_value = headers.get("Retry-After")
    if raw_value is None:
        return None

    try:
        # 负数没有可执行语义，按立即重试处理。
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _download_error_label(error: OSError | httpx.HTTPError) -> str:
    """生成不含请求 URL、响应正文或凭据的失败日志标签。"""

    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return type(error).__name__


class ImageFetcher:
    """带图片完整性校验和并发合并的运行期下载器。"""

    _MAX_ATTEMPTS = 3

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._build_client
        self._sleep = sleep or asyncio.sleep
        self._inflight: dict[tuple[str, Path], asyncio.Task[Path]] = {}
        self._inflight_lock = asyncio.Lock()

    @staticmethod
    def _build_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(follow_redirects=True, timeout=30)

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599

    @staticmethod
    def _is_valid_cached_image(target: Path) -> bool:
        if not target.exists():
            if target.is_symlink():
                raise ImageFetchError(f"图片缓存目标是符号链接: {target}")
            return False
        if target.is_symlink() or not target.is_file():
            raise ImageFetchError(f"图片缓存目标不是普通文件: {target}")
        try:
            _validate_image_file(target)
        except ImageFetchError:
            return False
        return True

    @staticmethod
    def _remove_invalid_cached_file(target: Path) -> None:
        if not target.exists() and not target.is_symlink():
            return
        if target.is_symlink() or not target.is_file():
            raise ImageFetchError(f"图片缓存目标不是普通文件: {target}")
        try:
            target.unlink()
        except OSError as exc:
            raise ImageFetchError(f"无法清理损坏图片缓存: {target}") from exc

    async def _download_content(self, url: str) -> bytes:
        if not url.startswith(("http://", "https://")):
            raise ImageFetchError("图片 URL 必须使用 HTTP(S)")

        async with self._client_factory() as client:
            for attempt in range(self._MAX_ATTEMPTS):
                try:
                    response = await client.get(url)
                except httpx.TransportError:
                    if attempt == self._MAX_ATTEMPTS - 1:
                        raise
                    await self._sleep(float(2**attempt))
                    continue

                if self._is_retryable_status(response.status_code):
                    if attempt == self._MAX_ATTEMPTS - 1:
                        response.raise_for_status()
                    delay = _retry_after_seconds(response.headers)
                    await self._sleep(delay if delay is not None else float(2**attempt))
                    continue

                response.raise_for_status()
                if not response.content:
                    raise ImageFetchError("图片响应为空")
                return response.content

        raise ImageFetchError("图片下载未完成")

    @staticmethod
    def _write_atomically(target: Path, content: bytes) -> None:
        if target.parent.is_symlink():
            raise ImageFetchError("图片缓存目录不能是符号链接")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise ImageFetchError("图片缓存目录不能是符号链接")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
            _validate_image_file(temporary_path)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    async def _fetch_to_target(self, url: str, target: Path, tag: str) -> Path:
        try:
            if self._is_valid_cached_image(target):
                return target
            self._remove_invalid_cached_file(target)
            content = await self._download_content(url)
            self._write_atomically(target, content)
        except (OSError, httpx.HTTPError) as exc:
            logger.warning(f"{tag} 下载失败: {target.name} ({_download_error_label(exc)})")
            raise
        logger.info(f"{tag} 下载完成: {target.name} ({len(content)}B)")
        return target

    async def _run_shared_fetch(
        self,
        key: tuple[str, Path],
        url: str,
        target: Path,
        tag: str,
    ) -> Path:
        try:
            return await self._fetch_to_target(url, target, tag)
        finally:
            current_task = asyncio.current_task()
            async with self._inflight_lock:
                if current_task is not None and self._inflight.get(key) is current_task:
                    del self._inflight[key]

    @staticmethod
    def _observe_task(task: asyncio.Task[Path]) -> None:
        """取消所有等待者后仍消费共享任务异常，避免后台任务泄漏告警。"""

        if not task.cancelled():
            task.exception()

    async def fetch(self, url: str, target: Path, tag: str = "") -> Path:
        """下载并校验图片；相同 URL 与目标路径的并发请求共享一个任务。"""

        target = Path(target)
        if self._is_valid_cached_image(target):
            return target

        key = (url, target.resolve())
        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None or task.done():
                task = asyncio.create_task(self._run_shared_fetch(key, url, target, tag))
                task.add_done_callback(self._observe_task)
                self._inflight[key] = task
        # 单个调用方取消时不应连带取消仍被其他调用方使用的下载任务。
        return await asyncio.shield(task)


_DEFAULT_IMAGE_FETCHER = ImageFetcher()


def _resolve_download_target(path: Path, name: str) -> Path:
    """解析兼容入口的目标，拒绝通过文件名越出调用方缓存目录。"""

    if path.is_symlink():
        raise ImageFetchError("图片缓存目录不能是符号链接")
    base = path.resolve()
    target = path / name
    try:
        target.resolve().relative_to(base)
    except ValueError as exc:
        raise ImageFetchError("图片缓存目标必须位于指定目录内") from exc
    try:
        relative_parts = target.relative_to(path).parts
    except ValueError as exc:
        raise ImageFetchError("图片缓存目标必须位于指定目录内") from exc
    cursor = path
    for component in relative_parts[:-1]:
        cursor /= component
        if cursor.is_symlink():
            raise ImageFetchError("图片缓存目录不能是符号链接")
    return target


async def download(
    url: str,
    path: Path,
    name: str,
    tag: str = "",
) -> Path:
    """下载 url 到 ``path/name``，保留 legacy 调用方的参数形状。"""

    target = _resolve_download_target(path, name)
    return await _DEFAULT_IMAGE_FETCHER.fetch(url, target, tag=tag)



async def get_event_avatar(
    ev: EventContext,
    avatar_path: Path,
    size: int = 640,
) -> Image.Image:
    """获取事件用户头像（QQ 头像源），缓存到 avatar_path。

    失败时抛异常，由调用方决定兜底（如使用默认立绘）。
    """
    uid = ev.at or ev.user_id
    avatar_path.mkdir(parents=True, exist_ok=True)
    name = f"avatar_{uid}.png"
    target = avatar_path / name
    url = f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s={size}"
    await download(url, avatar_path, name, tag="[DNA-avatar]")
    img = Image.open(target).convert("RGBA")
    return img.resize((size, size), Image.Resampling.LANCZOS)


class _ImageComponent(Protocol):
    """AstrBot 图片组件提供的最小转换接口。"""

    async def convert_to_file_path(self) -> str: ...


async def change_ev_image_to_bytes(
    image_source: _ImageComponent | str | bytes | Path,
) -> bytes:
    """URL / 本地路径 / bytes → bytes（自定义面板图上传用）。"""
    if isinstance(image_source, bytes):
        return image_source
    if isinstance(image_source, Path):
        return image_source.read_bytes()
    if not isinstance(image_source, str):
        image_path = await image_source.convert_to_file_path()
        return Path(image_path).read_bytes()
    s = image_source
    if s.startswith(("http://", "https://")):
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(s)
            resp.raise_for_status()
            return resp.content
    return Path(s).read_bytes()


async def get_qrcode_base64(url: str, path: Path, name: str) -> bytes:
    """以 HTML/T2I 生成扫码登录二维码，保留旧参数与返回类型。"""

    del path, name
    from ..infrastructure.rendering.qr import render_qr_code

    return await render_qr_code(url)
