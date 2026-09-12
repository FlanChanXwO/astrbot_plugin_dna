"""共享图片下载器契约测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from src.utils.image_utils import ImageFetcher, ImageFetcherClosed, ImageFetchError


def _png_bytes(color: str = "#4f46e5") -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (2, 2), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _response(
    url: str,
    content: bytes,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=content,
        headers=headers,
        request=httpx.Request("GET", url),
    )


class _FakeClient:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.handler: Any = None
        self.closed = False

    async def get(self, url: str, **_kwargs: object) -> httpx.Response:
        self.calls.append(url)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.handler is not None:
                outcome = self.handler(url)
                if hasattr(outcome, "__await__"):
                    outcome = await outcome
            else:
                outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        finally:
            self.active -= 1

    async def aclose(self) -> None:
        self.closed = True


class _ClientFactory:
    def __init__(self, clients: list[_FakeClient]) -> None:
        self.clients = clients
        self.calls = 0

    def __call__(self) -> _FakeClient:
        client = self.clients[min(self.calls, len(self.clients) - 1)]
        self.calls += 1
        return client


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_fetch_uses_one_long_lived_client_for_multiple_urls(
    tmp_path: Path,
) -> None:
    """多个 URL 复用同一个 client，关闭时只释放一次。"""

    first_url = "https://cdn.example.test/first.png"
    second_url = "https://cdn.example.test/second.png"
    client = _FakeClient(
        [
            _response(first_url, _png_bytes()),
            _response(second_url, _png_bytes("#22c55e")),
        ]
    )
    factory = _ClientFactory([client])
    fetcher = ImageFetcher(client_factory=factory, sleep=_no_sleep)

    await fetcher.start()
    await fetcher.fetch(first_url, tmp_path / "first.png")
    await fetcher.fetch(second_url, tmp_path / "second.png")
    await fetcher.close()

    assert factory.calls == 1
    assert client.closed


@pytest.mark.asyncio
async def test_same_url_fans_out_to_distinct_targets(tmp_path: Path) -> None:
    """相同 URL 的不同目标共享一次网络请求，但各自原子落盘。"""

    url = "https://cdn.example.test/shared.png"
    client = _FakeClient()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(request_url: str) -> httpx.Response:
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    client.handler = blocking_handler
    fetcher = ImageFetcher(client_factory=_ClientFactory([client]), sleep=_no_sleep)
    first_target = tmp_path / "one.png"
    second_target = tmp_path / "two.png"

    first = asyncio.create_task(fetcher.fetch(url, first_target))
    await started.wait()
    second = asyncio.create_task(fetcher.fetch(url, second_target))
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(first, second) == [first_target, second_target]
    assert client.calls == [url]
    with Image.open(first_target) as image:
        image.verify()
    with Image.open(second_target) as image:
        image.verify()
    await fetcher.close()


@pytest.mark.asyncio
async def test_different_urls_run_concurrently(tmp_path: Path) -> None:
    """不同 URL 在动态容量允许时可同时占用 HTTP 请求槽位。"""

    urls = [
        "https://cdn.example.test/one.png",
        "https://cdn.example.test/two.png",
    ]
    client = _FakeClient()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(url: str) -> httpx.Response:
        if client.active >= 2:
            started.set()
        await release.wait()
        return _response(url, _png_bytes())

    client.handler = blocking_handler
    fetcher = ImageFetcher(
        client_factory=_ClientFactory([client]),
        sleep=_no_sleep,
        initial_capacity=2,
    )
    tasks = [
        asyncio.create_task(fetcher.fetch(url, tmp_path / f"{index}.png"))
        for index, url in enumerate(urls)
    ]

    await started.wait()
    release.set()
    await asyncio.gather(*tasks)

    assert client.max_active == 2
    await fetcher.close()


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_and_shrinks_capacity(
    tmp_path: Path,
) -> None:
    """429 优先使用 Retry-After，并立即降低自适应容量。"""

    url = "https://cdn.example.test/rate-limited.png"
    client = _FakeClient(
        [
            _response(url, b"busy", status_code=429, headers={"Retry-After": "7"}),
            _response(url, _png_bytes()),
        ]
    )
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    fetcher = ImageFetcher(
        client_factory=_ClientFactory([client]),
        sleep=record_sleep,
        initial_capacity=4,
    )

    await fetcher.fetch(url, tmp_path / "rate-limited.png")

    assert sleeps == [7.0]
    assert fetcher.capacity == 2
    await fetcher.close()


@pytest.mark.asyncio
async def test_close_wakes_long_retry_after_without_cancelling_http_request(
    tmp_path: Path,
) -> None:
    """关闭时应唤醒 Retry-After 等待，并清理共享任务与 client。"""

    url = "https://cdn.example.test/long-retry.png"
    client = _FakeClient(
        [_response(url, b"busy", status_code=429, headers={"Retry-After": "86400"})]
    )
    sleep_started = asyncio.Event()
    release_sleep = asyncio.Event()

    async def blocking_sleep(_delay: float) -> None:
        sleep_started.set()
        await release_sleep.wait()

    fetcher = ImageFetcher(
        client_factory=_ClientFactory([client]),
        sleep=blocking_sleep,
    )
    fetch_task = asyncio.create_task(fetcher.fetch(url, tmp_path / "long-retry.png"))
    await sleep_started.wait()

    close_task = asyncio.create_task(fetcher.close())
    try:
        await asyncio.wait_for(asyncio.shield(close_task), timeout=0.2)
    except TimeoutError:
        # 当前实现会卡在注入的 Retry-After sleep；释放测试睡眠仅用于清理，
        # 断言本身要求 close 能被关闭信号唤醒。
        release_sleep.set()
        await asyncio.gather(fetch_task, return_exceptions=True)
        await close_task
        pytest.fail("close 不应等待完整 Retry-After sleep")

    with pytest.raises(ImageFetcherClosed):
        await fetch_task

    assert client.calls == [url]
    assert client.closed
    assert fetcher.active_requests == 0
    assert fetcher.inflight_count == 0


@pytest.mark.asyncio
async def test_healthy_requests_recover_capacity(tmp_path: Path) -> None:
    """连续健康请求逐步恢复容量，但不超过内部上限。"""

    urls = [f"https://cdn.example.test/{index}.png" for index in range(6)]
    client = _FakeClient([_response(url, _png_bytes()) for url in urls])
    fetcher = ImageFetcher(
        client_factory=_ClientFactory([client]),
        sleep=_no_sleep,
        initial_capacity=1,
        max_capacity=4,
    )

    await asyncio.gather(
        *(
            fetcher.fetch(url, tmp_path / f"{index}.png")
            for index, url in enumerate(urls)
        )
    )

    assert fetcher.capacity > 1
    assert fetcher.capacity <= 4
    await fetcher.close()


@pytest.mark.asyncio
async def test_weak_errors_accumulate_before_capacity_shrink(tmp_path: Path) -> None:
    """单次弱错误不震荡，同一窗口内多个 5xx 才收缩容量。"""

    stable_url = "https://cdn.example.test/stable-weak.png"
    stable_client = _FakeClient(
        [
            _response(stable_url, b"busy", status_code=503),
            _response(stable_url, _png_bytes()),
        ]
    )
    stable_fetcher = ImageFetcher(
        client_factory=_ClientFactory([stable_client]),
        sleep=_no_sleep,
        initial_capacity=4,
    )

    await stable_fetcher.fetch(stable_url, tmp_path / "stable.png")
    assert stable_fetcher.capacity == 4
    await stable_fetcher.close()

    congested_url = "https://cdn.example.test/congested.png"
    congested_client = _FakeClient(
        [
            _response(congested_url, b"busy", status_code=503),
            _response(congested_url, b"still-busy", status_code=503),
            _response(congested_url, _png_bytes()),
        ]
    )
    congested_fetcher = ImageFetcher(
        client_factory=_ClientFactory([congested_client]),
        sleep=_no_sleep,
        initial_capacity=4,
    )

    await congested_fetcher.fetch(congested_url, tmp_path / "congested.png")
    assert congested_fetcher.capacity == 2
    await congested_fetcher.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_fanout(tmp_path: Path) -> None:
    """一个 waiter 取消时，URL 共享任务仍服务其他目标。"""

    url = "https://cdn.example.test/cancellable.png"
    client = _FakeClient()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(request_url: str) -> httpx.Response:
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    client.handler = blocking_handler
    fetcher = ImageFetcher(client_factory=_ClientFactory([client]), sleep=_no_sleep)
    first_target = tmp_path / "cancelled.png"
    second_target = tmp_path / "survivor.png"
    first = asyncio.create_task(fetcher.fetch(url, first_target))
    await started.wait()
    second = asyncio.create_task(fetcher.fetch(url, second_target))
    await asyncio.sleep(0)
    first.cancel()

    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()

    assert await second == second_target
    assert client.calls == [url]
    await fetcher.close()


@pytest.mark.asyncio
async def test_close_drains_active_requests_and_rejects_new_work(
    tmp_path: Path,
) -> None:
    """关闭先拒绝新下载，再等待 active HTTP 自然完成并释放 client。"""

    url = "https://cdn.example.test/draining.png"
    client = _FakeClient()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(request_url: str) -> httpx.Response:
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    client.handler = blocking_handler
    fetcher = ImageFetcher(client_factory=_ClientFactory([client]), sleep=_no_sleep)
    active_target = tmp_path / "active.png"
    fetch_task = asyncio.create_task(fetcher.fetch(url, active_target))
    await started.wait()

    close_task = asyncio.create_task(fetcher.close())
    await asyncio.sleep(0)
    assert not close_task.done()
    assert not client.closed

    with pytest.raises(ImageFetcherClosed):
        await fetcher.fetch(url, tmp_path / "rejected.png")

    release.set()
    assert await fetch_task == active_target
    await close_task
    assert client.closed
    assert fetcher.active_requests == 0
    assert fetcher.inflight_count == 0


@pytest.mark.asyncio
async def test_cancelled_close_finishes_cleanup_and_propagates_cancellation(
    tmp_path: Path,
) -> None:
    """取消 close 等待时仍必须完成清理，并把取消重新交给调用方。"""

    url = "https://cdn.example.test/cancelled-close.png"
    client = _FakeClient()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(request_url: str) -> httpx.Response:
        started.set()
        await release.wait()
        return _response(request_url, _png_bytes())

    client.handler = blocking_handler
    fetcher = ImageFetcher(client_factory=_ClientFactory([client]), sleep=_no_sleep)
    target = tmp_path / "cancelled-close.png"
    fetch_task = asyncio.create_task(fetcher.fetch(url, target))
    await started.wait()

    close_task = asyncio.create_task(fetcher.close())
    await asyncio.sleep(0)
    close_task.cancel()
    release.set()

    assert await fetch_task == target
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert client.closed
    assert fetcher.active_requests == 0
    assert fetcher.inflight_count == 0


@pytest.mark.asyncio
async def test_restart_after_close_creates_new_client(tmp_path: Path) -> None:
    """stop/reload 后可重新启动并创建新的长生命周期 client。"""

    first_url = "https://cdn.example.test/reload-first.png"
    second_url = "https://cdn.example.test/reload-second.png"
    clients = [
        _FakeClient([_response(first_url, _png_bytes())]),
        _FakeClient([_response(second_url, _png_bytes("#22c55e"))]),
    ]
    factory = _ClientFactory(clients)
    fetcher = ImageFetcher(client_factory=factory, sleep=_no_sleep)

    await fetcher.start()
    await fetcher.fetch(first_url, tmp_path / "first.png")
    await fetcher.close()
    await fetcher.start()
    await fetcher.fetch(second_url, tmp_path / "second.png")
    await fetcher.close()

    assert factory.calls == 2
    assert all(client.closed for client in clients)


@pytest.mark.asyncio
async def test_fetch_retries_transient_errors_and_keeps_invalid_content_out_of_cache(
    tmp_path: Path,
) -> None:
    """保留传输重试和完整图片校验契约。"""

    url = "https://cdn.example.test/retry.png"
    request = httpx.Request("GET", url)
    client = _FakeClient(
        [
            httpx.ConnectError("offline", request=request),
            httpx.ReadTimeout("timeout", request=request),
            _response(url, _png_bytes()),
        ]
    )
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    fetcher = ImageFetcher(
        client_factory=_ClientFactory([client]),
        sleep=record_sleep,
    )
    target = tmp_path / "retry.png"

    assert await fetcher.fetch(url, target) == target
    assert sleeps == [1.0, 2.0]
    await fetcher.close()

    bad_url = "https://cdn.example.test/bad.png"
    bad_client = _FakeClient([_response(bad_url, b"not-an-image")])
    bad_fetcher = ImageFetcher(
        client_factory=_ClientFactory([bad_client]),
        sleep=_no_sleep,
    )
    with pytest.raises(ImageFetchError):
        await bad_fetcher.fetch(bad_url, tmp_path / "bad.png")
    assert not (tmp_path / "bad.png").exists()
    await bad_fetcher.close()
