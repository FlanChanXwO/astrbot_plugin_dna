"""O09 图片下载器契约测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.utils import image_utils
from src.utils.image import download_pic_from_url, get_avatar_img
from src.utils.image_utils import ImageFetcher, ImageFetchError, get_event_avatar
from src.utils.session import EventContext


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (2, 2), "#4f46e5").save(buffer, format="PNG")
    return buffer.getvalue()


def _response(
    url: str,
    content: bytes,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
):
    return httpx.Response(
        status_code,
        content=content,
        headers=headers,
        request=httpx.Request("GET", url),
    )


class _FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, url: str, **kwargs: object):
        del kwargs
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _ClientFactory:
    def __init__(self, outcomes):
        self.client = _FakeClient(outcomes)

    def __call__(self):
        return self.client


@pytest.mark.asyncio
async def test_fetch_retries_transient_errors_with_backoff(tmp_path: Path):
    url = "https://cdn.example.test/avatar.png"
    request = httpx.Request("GET", url)
    factory = _ClientFactory(
        [
            httpx.ConnectError("offline", request=request),
            httpx.ReadTimeout("timeout", request=request),
            _response(url, _png_bytes()),
        ],
    )
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    target = tmp_path / "avatar.png"
    result = await ImageFetcher(client_factory=factory, sleep=fake_sleep).fetch(
        url, target
    )

    assert result == target
    assert factory.client.calls == 3
    assert sleeps == [1, 2]
    with Image.open(target) as image:
        image.verify()


@pytest.mark.asyncio
async def test_fetch_honors_retry_after_for_rate_limit(tmp_path: Path):
    url = "https://cdn.example.test/rate-limited.png"
    factory = _ClientFactory(
        [
            _response(url, b"busy", status_code=429, headers={"Retry-After": "7"}),
            _response(url, _png_bytes()),
        ],
    )
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    await ImageFetcher(client_factory=factory, sleep=fake_sleep).fetch(
        url,
        tmp_path / "rate-limited.png",
    )

    assert factory.client.calls == 2
    assert sleeps == [7]


@pytest.mark.asyncio
async def test_fetch_retries_server_errors_twice(tmp_path: Path):
    url = "https://cdn.example.test/server-error.png"
    factory = _ClientFactory(
        [
            _response(url, b"temporary", status_code=503),
            _response(url, b"temporary", status_code=502),
            _response(url, _png_bytes()),
        ],
    )
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    await ImageFetcher(client_factory=factory, sleep=fake_sleep).fetch(
        url,
        tmp_path / "server-error.png",
    )

    assert factory.client.calls == 3
    assert sleeps == [1, 2]


@pytest.mark.asyncio
async def test_fetch_does_not_retry_http_error_or_write_placeholder(tmp_path: Path):
    url = "https://cdn.example.test/missing.png"
    factory = _ClientFactory([_response(url, b"missing", status_code=404)])
    target = tmp_path / "missing.png"

    with pytest.raises(httpx.HTTPStatusError):
        await ImageFetcher(
            client_factory=factory, sleep=lambda _: asyncio.sleep(0)
        ).fetch(
            url,
            target,
        )

    assert factory.client.calls == 1
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_fetch_failure_log_does_not_include_signed_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://cdn.example.test/missing.png?token=secret-image-token"
    factory = _ClientFactory([_response(url, b"forbidden", status_code=403)])
    messages: list[str] = []
    monkeypatch.setattr(image_utils.logger, "warning", messages.append)

    with pytest.raises(httpx.HTTPStatusError):
        await ImageFetcher(
            client_factory=factory, sleep=lambda _: asyncio.sleep(0)
        ).fetch(
            url,
            tmp_path / "missing.png",
        )

    assert messages == [" 下载失败: missing.png (HTTP 403)"]
    assert "secret-image-token" not in messages[0]


@pytest.mark.asyncio
async def test_download_rejects_path_escape(tmp_path: Path):
    with pytest.raises(ImageFetchError):
        await image_utils.download(
            "https://cdn.example.test/escape.png",
            tmp_path,
            "../escape.png",
        )

    assert not (tmp_path.parent / "escape.png").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"not-an-image"])
async def test_fetch_rejects_invalid_content_without_cache_file(
    tmp_path: Path, content: bytes
):
    url = "https://cdn.example.test/broken.png"
    factory = _ClientFactory([_response(url, content)])
    target = tmp_path / "broken.png"

    with pytest.raises(ImageFetchError):
        await ImageFetcher(
            client_factory=factory, sleep=lambda _: asyncio.sleep(0)
        ).fetch(
            url,
            target,
        )

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_fetch_revalidates_existing_corrupt_file_before_reuse(tmp_path: Path):
    url = "https://cdn.example.test/recoverable.png"
    target = tmp_path / "recoverable.png"
    target.write_bytes(b"corrupt-cache")
    factory = _ClientFactory([_response(url, _png_bytes())])

    await ImageFetcher(client_factory=factory, sleep=lambda _: asyncio.sleep(0)).fetch(
        url, target
    )

    assert factory.client.calls == 1
    with Image.open(target) as image:
        image.verify()


@pytest.mark.asyncio
async def test_legacy_image_helper_revalidates_existing_corrupt_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://cdn.example.test/helper.png"
    target = tmp_path / "helper.png"
    target.write_bytes(b"corrupt-cache")
    calls: list[str] = []

    async def fake_download(
        download_url: str, path: Path, name: str, tag: str = ""
    ) -> Path:
        calls.append(download_url)
        del tag
        downloaded = path / name
        downloaded.write_bytes(_png_bytes())
        return downloaded

    monkeypatch.setattr("src.utils.image.download", fake_download)

    await download_pic_from_url(tmp_path, url, name=target.name)

    assert calls == [url]
    with Image.open(target) as image:
        image.verify()


@pytest.mark.asyncio
async def test_event_avatar_revalidates_existing_corrupt_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "avatar_user-1.png"
    target.write_bytes(b"corrupt-cache")
    calls: list[str] = []

    async def fake_download(
        download_url: str, path: Path, name: str, tag: str = ""
    ) -> Path:
        calls.append(download_url)
        del tag
        downloaded = path / name
        downloaded.write_bytes(_png_bytes())
        return downloaded

    monkeypatch.setattr(image_utils, "download", fake_download)

    image = await get_event_avatar(EventContext(user_id="user-1"), tmp_path, size=2)

    assert calls == ["https://q1.qlogo.cn/g?b=qq&nk=user-1&s=2"]
    assert image.size == (2, 2)


@pytest.mark.asyncio
async def test_optional_image_does_not_follow_rejected_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(_png_bytes())
    (cache_dir / "avatar_42.png").symlink_to(outside_image)
    monkeypatch.setattr("src.utils.image.AVATAR_PATH", cache_dir)

    async def reject_download(*args: object, **kwargs: object) -> Path:
        del args, kwargs
        raise ImageFetchError("图片缓存目标是符号链接")

    monkeypatch.setattr("src.utils.image.download", reject_download)

    image = await get_avatar_img(42, "https://cdn.example.test/avatar.png")

    assert image.size == (256, 256)


@pytest.mark.asyncio
async def test_fetch_single_flights_same_url_and_target(tmp_path: Path):
    url = "https://cdn.example.test/shared.png"
    started = asyncio.Event()
    release = asyncio.Event()
    target = tmp_path / "shared.png"
    factory = _ClientFactory([])

    async def blocking_get(request_url: str, **kwargs: object):
        del kwargs
        factory.client.calls += 1
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    factory.client.get = blocking_get
    fetcher = ImageFetcher(client_factory=factory, sleep=lambda _: asyncio.sleep(0))
    first = asyncio.create_task(fetcher.fetch(url, target))
    await started.wait()
    second = asyncio.create_task(fetcher.fetch(url, target))
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(first, second) == [target, target]
    assert factory.client.calls == 1


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_fetch(tmp_path: Path):
    url = "https://cdn.example.test/cancellable.png"
    started = asyncio.Event()
    release = asyncio.Event()
    target = tmp_path / "cancellable.png"
    factory = _ClientFactory([])

    async def blocking_get(request_url: str, **kwargs: object):
        del kwargs
        factory.client.calls += 1
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    factory.client.get = blocking_get
    fetcher = ImageFetcher(client_factory=factory, sleep=lambda _: asyncio.sleep(0))
    first = asyncio.create_task(fetcher.fetch(url, target))
    await started.wait()
    second = asyncio.create_task(fetcher.fetch(url, target))
    await asyncio.sleep(0)
    first.cancel()

    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()

    assert await second == target
    assert factory.client.calls == 1
