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
import inspect
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
    "ImageFetcherClosed",
    "change_ev_image_to_bytes",
    "convert_img",
    "crop_center_img",
    "download",
    "get_default_image_fetcher",
    "get_event_avatar",
    "get_qrcode_base64",
    "set_default_image_fetcher",
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


class ImageFetcherClosed(ImageFetchError):
    """下载器已停止，不再接纳新的网络下载。"""


def _validate_image_file(path: Path) -> None:
    """完整解码图片，避免把 HTML、空响应或损坏文件当作缓存成功。"""

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageFetchError(f"图片不可解码: {path.name}") from exc


def _validate_image_bytes(content: bytes) -> None:
    """在 URL 共享任务中先校验一次响应，避免把坏内容 fan-out 到缓存。"""

    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageFetchError("图片响应不是可解码图片") from exc


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


class _AdaptiveCapacity:
    """按请求结果动态调整的内部 HTTP 并发容量。"""

    _WEAK_CONGESTION_THRESHOLD = 2
    _HEALTHY_REQUEST_WINDOW = 4

    def __init__(
        self,
        *,
        initial: int,
        minimum: int,
        maximum: int,
    ) -> None:
        self._minimum = minimum
        self._maximum = maximum
        self._initial = initial
        self._capacity = initial
        self._active = 0
        self._healthy_requests = 0
        self._weak_congestion = 0
        self._condition = asyncio.Condition()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def active(self) -> int:
        return self._active

    async def acquire(self) -> None:
        async with self._condition:
            while self._active >= self._capacity:
                await self._condition.wait()
            self._active += 1

    async def release(
        self,
        *,
        success: bool = False,
        congestion: str | None = None,
    ) -> None:
        async with self._condition:
            if self._active <= 0:
                raise RuntimeError("图片下载并发槽位释放次数不匹配")
            self._active -= 1
            if congestion == "strong":
                self._capacity = max(self._minimum, self._capacity // 2)
                self._healthy_requests = 0
                self._weak_congestion = 0
            elif congestion == "weak":
                self._healthy_requests = 0
                self._weak_congestion += 1
                if self._weak_congestion >= self._WEAK_CONGESTION_THRESHOLD:
                    self._capacity = max(self._minimum, self._capacity // 2)
                    self._weak_congestion = 0
            elif success:
                self._weak_congestion = 0
                self._healthy_requests += 1
                if self._healthy_requests >= self._HEALTHY_REQUEST_WINDOW:
                    self._capacity = min(self._maximum, self._capacity + 1)
                    self._healthy_requests = 0
            self._condition.notify_all()

    def reset(self) -> None:
        if self._active:
            raise RuntimeError("不能在图片请求进行时重置并发容量")
        self._capacity = self._initial
        self._healthy_requests = 0
        self._weak_congestion = 0


class ImageFetcher:
    """带生命周期、动态并发、URL 合并和原子校验的运行期图片下载器。"""

    _MAX_ATTEMPTS = 3
    _MIN_CAPACITY = 1
    _DEFAULT_INITIAL_CAPACITY = 8
    _MAX_CAPACITY = 64

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        initial_capacity: int = _DEFAULT_INITIAL_CAPACITY,
        max_capacity: int = _MAX_CAPACITY,
    ) -> None:
        # 仅作为内部连接数安全边界，避免无限扩大 client 连接池；不暴露为用户配置。
        maximum = min(self._MAX_CAPACITY, int(max_capacity))
        initial = int(initial_capacity)
        if maximum < self._MIN_CAPACITY:
            raise ValueError("图片下载并发上限必须至少为 1")
        if not self._MIN_CAPACITY <= initial <= maximum:
            raise ValueError("图片下载初始并发必须位于有效上限内")

        self._client_factory = client_factory or self._build_client
        self._sleep = sleep or asyncio.sleep
        self._max_capacity = maximum
        self._capacity = _AdaptiveCapacity(
            initial=initial,
            minimum=self._MIN_CAPACITY,
            maximum=maximum,
        )
        self._inflight: dict[str, asyncio.Task[bytes]] = {}
        self._active_tasks: set[asyncio.Task[bytes]] = set()
        self._condition = asyncio.Condition()
        self._client_lock = asyncio.Lock()
        self._client: Any | None = None
        self._starting = False
        self._closing = False
        self._closing_event = asyncio.Event()
        self._accepting = True
        self._closed = False

    @property
    def capacity(self) -> int:
        """当前允许的 HTTP 并发容量，供运行期观测和测试使用。"""

        return self._capacity.capacity

    @property
    def active_requests(self) -> int:
        """当前占用 HTTP 并发槽位的请求数。"""

        return self._capacity.active

    @property
    def inflight_count(self) -> int:
        """当前按 URL 合并的共享下载任务数。"""

        return len(self._inflight)

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=False,
            timeout=30,
            limits=httpx.Limits(
                max_connections=self._max_capacity,
                max_keepalive_connections=self._max_capacity,
            ),
        )

    async def _get_client(self) -> Any:
        async with self._client_lock:
            if self._client is None:
                client = self._client_factory()
                if inspect.isawaitable(client):
                    client = await client
                self._client = client
            return self._client

    @staticmethod
    async def _close_client(client: Any | None) -> None:
        if client is None:
            return
        close = getattr(client, "aclose", None)
        if not callable(close):
            close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
            return
        exit_context = getattr(client, "__aexit__", None)
        if callable(exit_context):
            result = exit_context(None, None, None)
            if inspect.isawaitable(result):
                await result

    async def start(self) -> None:
        """启动下载器并预先创建长生命周期 HTTP client。"""

        async with self._condition:
            while self._closing:
                await self._condition.wait()
            if self._accepting and not self._closed:
                if self._client is not None:
                    return
            else:
                self._capacity.reset()
            self._accepting = True
            self._closed = False
            self._closing_event.clear()
            self._starting = True
        try:
            await self._get_client()
        except BaseException:
            async with self._condition:
                self._starting = False
                self._accepting = False
                self._closed = True
                self._condition.notify_all()
            raise
        async with self._condition:
            self._starting = False
            self._condition.notify_all()

    async def close(self) -> None:
        """拒绝新下载，等待 active HTTP 自然结束后关闭共享 client。"""

        claimed_closing = False
        client: Any | None = None
        try:
            async with self._condition:
                if self._closing:
                    while self._closing:
                        await self._condition.wait()
                    return
                if (
                    self._closed
                    and self._client is None
                    and not self._starting
                    and not self._active_tasks
                ):
                    return
                self._closing = True
                claimed_closing = True
                self._accepting = False
                self._closed = True
                self._closing_event.set()
                while self._starting or self._active_tasks:
                    await self._condition.wait()
                client = self._client
                self._client = None
                self._inflight.clear()
            # shield 让调用方取消 close 时，底层 client 仍能完成释放。
            await asyncio.shield(self._close_client(client))
        finally:
            if claimed_closing:
                async with self._condition:
                    self._closing = False
                    self._condition.notify_all()

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

        client = await self._get_client()
        for attempt in range(self._MAX_ATTEMPTS):
            await self._capacity.acquire()
            congestion: str | None = None
            healthy = False
            slot_released = False
            try:
                try:
                    response = await client.get(url, follow_redirects=False)
                except httpx.TransportError:
                    congestion = "weak"
                    if attempt == self._MAX_ATTEMPTS - 1:
                        raise
                    await self._release_capacity(
                        success=False,
                        congestion=congestion,
                    )
                    slot_released = True
                    congestion = None
                    await self._wait_for_retry(float(2**attempt))
                    continue

                if response.status_code == 429:
                    congestion = "strong"
                elif 500 <= response.status_code <= 599:
                    congestion = "weak"
                else:
                    healthy = True

                if self._is_retryable_status(response.status_code):
                    if attempt == self._MAX_ATTEMPTS - 1:
                        response.raise_for_status()
                    delay = _retry_after_seconds(response.headers)
                    await self._release_capacity(
                        success=False,
                        congestion=congestion,
                    )
                    slot_released = True
                    congestion = None
                    await self._wait_for_retry(
                        delay if delay is not None else float(2**attempt)
                    )
                    continue

                if 300 <= response.status_code < 400:
                    raise ImageFetchError("图片下载不允许重定向")
                response.raise_for_status()
                if not response.content:
                    raise ImageFetchError("图片响应为空")
                _validate_image_bytes(response.content)
                return response.content
            finally:
                if not slot_released:
                    await self._release_capacity(
                        success=healthy,
                        congestion=congestion,
                    )

        raise ImageFetchError("图片下载未完成")

    async def _wait_for_retry(self, delay: float) -> None:
        """等待退避或关闭信号，避免 stop 被 Retry-After 长时间阻塞。"""

        if self._closing_event.is_set():
            raise ImageFetcherClosed("图片下载器已停止")

        sleep_task = asyncio.create_task(self._sleep(delay))
        closing_task = asyncio.create_task(self._closing_event.wait())
        try:
            done, _ = await asyncio.wait(
                (sleep_task, closing_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if closing_task in done and closing_task.result():
                raise ImageFetcherClosed("图片下载器已停止")
            await sleep_task
        finally:
            for task in (sleep_task, closing_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleep_task, closing_task, return_exceptions=True)

    async def _release_capacity(
        self,
        *,
        success: bool,
        congestion: str | None,
    ) -> None:
        # 共享任务不应因单个 waiter 取消而遗留并发槽位。
        await asyncio.shield(
            self._capacity.release(success=success, congestion=congestion)
        )

    @staticmethod
    def _write_atomically(target: Path, content: bytes) -> None:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ImageFetchError(f"图片缓存目标不是普通文件: {target}")
        if target.parent.is_symlink():
            raise ImageFetchError("图片缓存目录不能是符号链接")
        if target.parent.exists() and not target.parent.is_dir():
            raise ImageFetchError("图片缓存目录不是目录")
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
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ImageFetchError(f"图片缓存目标不是普通文件: {target}")
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    async def _run_shared_download(
        self,
        url: str,
        target_name: str,
        tag: str,
    ) -> bytes:
        current_task = asyncio.current_task()
        try:
            content = await self._download_content(url)
        except (OSError, httpx.HTTPError) as exc:
            logger.warning(
                f"{tag} 下载失败: {target_name} ({_download_error_label(exc)})"
            )
            raise
        else:
            logger.info(f"{tag} 下载完成: {target_name} ({len(content)}B)")
            return content
        finally:
            async with self._condition:
                if current_task is not None and self._inflight.get(url) is current_task:
                    del self._inflight[url]
                if current_task is not None:
                    self._active_tasks.discard(current_task)
                self._condition.notify_all()

    @staticmethod
    def _observe_task(task: asyncio.Task[bytes]) -> None:
        """取消所有等待者后仍消费共享任务异常，避免后台任务泄漏告警。"""

        if not task.cancelled():
            task.exception()

    async def fetch(self, url: str, target: Path, tag: str = "") -> Path:
        """下载并校验图片；相同 URL 的不同目标共享一个任务。"""

        target = Path(target)
        if self._is_valid_cached_image(target):
            return target
        self._remove_invalid_cached_file(target)

        async with self._condition:
            if not self._accepting:
                raise ImageFetcherClosed("图片下载器已停止")
            task = self._inflight.get(url)
            if task is None or task.done():
                task = asyncio.create_task(
                    self._run_shared_download(url, target.name, tag)
                )
                task.add_done_callback(self._observe_task)
                self._inflight[url] = task
                self._active_tasks.add(task)

        # 单个调用方取消时不应连带取消仍被其他调用方使用的下载任务。
        content = await asyncio.shield(task)
        try:
            self._write_atomically(target, content)
        except (OSError, httpx.HTTPError) as exc:
            logger.warning(
                f"{tag} 缓存写入失败: {target.name} ({_download_error_label(exc)})"
            )
            raise
        return target


_DEFAULT_IMAGE_FETCHER = ImageFetcher()


def get_default_image_fetcher() -> ImageFetcher:
    """返回进程内共享的默认图片下载器。"""

    return _DEFAULT_IMAGE_FETCHER


def set_default_image_fetcher(fetcher: ImageFetcher) -> None:
    """替换默认下载器，供 runtime 注入测试或宿主生命周期实例。"""

    global _DEFAULT_IMAGE_FETCHER
    _DEFAULT_IMAGE_FETCHER = fetcher


def _resolve_download_target(path: Path, name: str) -> Path:
    """解析兼容入口的目标，拒绝通过文件名越出调用方缓存目录。"""

    if path.is_symlink() or path.parent.is_symlink():
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
    return await get_default_image_fetcher().fetch(url, target, tag=tag)


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
