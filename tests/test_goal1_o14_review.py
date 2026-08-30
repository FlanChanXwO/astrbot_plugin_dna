"""O14 第二阶段代码审查发现的安全与并发边界测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import httpx
import pytest

from src.infrastructure.http.notices import DnaApiNoticesTransport
from src.modules.player.contracts import RoleOverview
from src.utils import image_utils
from src.utils.image_utils import ImageFetcher, ImageFetchError
from tests.test_goal1_o10_player_cache import (
    MutableClock,
    _overview_fixture,
    _request,
    _service,
)


class _RedirectClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append(kwargs)
        return self.response


class _RedirectClientFactory:
    def __init__(self, response: httpx.Response) -> None:
        self.client = _RedirectClient(response)

    def __call__(self) -> _RedirectClient:
        return self.client


@pytest.mark.asyncio
async def test_image_fetcher_does_not_follow_redirects(tmp_path: Path) -> None:
    """图片下载不能把 HTTP 重定向自动跟到内网或 metadata 地址。"""

    default_client = ImageFetcher._build_client()
    assert default_client.follow_redirects is False
    await default_client.aclose()

    url = "https://cdn.example.test/image"
    response = httpx.Response(
        302,
        headers={"Location": "http://127.0.0.1:8080/secret"},
        request=httpx.Request("GET", url),
    )
    factory = _RedirectClientFactory(response)

    with pytest.raises(ImageFetchError, match="重定向"):
        await ImageFetcher(
            client_factory=factory,
            sleep=lambda _: asyncio.sleep(0),
        ).fetch(url, tmp_path / "image.png")

    assert factory.client.calls == [{"follow_redirects": False}]


@pytest.mark.asyncio
async def test_download_rejects_symlinked_ancestor_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缓存目录的祖先是符号链接时，不能沿链接写到指定目录外。"""

    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "cache-link"
    linked_root.symlink_to(outside, target_is_directory=True)
    nested_cache = linked_root / "nested"

    async def unexpected_fetch(*args: object, **kwargs: object) -> Path:
        del args, kwargs
        raise AssertionError("不安全路径不应进入下载器")

    monkeypatch.setattr(image_utils._DEFAULT_IMAGE_FETCHER, "fetch", unexpected_fetch)

    with pytest.raises(ImageFetchError, match="符号链接"):
        await image_utils.download(
            "https://cdn.example.test/image.png",
            nested_cache,
            "image.png",
        )

    assert not (outside / "nested" / "image.png").exists()


@pytest.mark.asyncio
async def test_ann_list_deduplicates_post_ids_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨页重复公告只保留首次出现的条目，避免序号和 fingerprint 污染。"""

    async def get_page(*, page_index: int, page_size: int) -> SimpleNamespace:
        assert page_size == 20
        if page_index == 1:
            posts = [
                {"postId": str(index), "postTitle": f"公告 {index}"}
                for index in range(1, 21)
            ]
        else:
            posts = [
                {"postId": "20", "postTitle": "重复公告的新版本"},
                {"postId": "21", "postTitle": "公告 21"},
            ]
        return SimpleNamespace(is_success=True, code=200, data={"postList": posts})

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_ann_list_page", get_page)
    snapshot = await DnaApiNoticesTransport.__new__(DnaApiNoticesTransport).get_ann_list()

    assert [post.post_id for post in snapshot.posts] == [str(index) for index in range(1, 22)]
    assert snapshot.posts[19].title == "公告 20"


@pytest.mark.asyncio
async def test_refresh_wins_over_older_inflight_overview_write(tmp_path: Path) -> None:
    """显式刷新完成后，较早开始的概览请求不能把旧数据写回缓存。"""

    clock = MutableClock()
    database, transport, _renderer, cache, service = await _service(tmp_path, clock)
    old_overview = _overview_fixture().model_copy(update={"role_name": "旧概览"})
    new_overview = _overview_fixture().model_copy(update={"role_name": "刷新概览"})
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    overview_calls = 0

    async def get_overview(*args: object, **kwargs: object) -> RoleOverview:
        del args, kwargs
        nonlocal overview_calls
        overview_calls += 1
        if overview_calls == 1:
            first_started.set()
            await release_first.wait()
            return old_overview
        return new_overview

    transport.get_overview = get_overview
    service.refresh_send_card = False
    try:
        stale_query = asyncio.create_task(service.role_overview(_request()))
        await first_started.wait()
        refresh = asyncio.create_task(
            service.refresh_role(_request(detail=True), uid="1234567890123"),
        )
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(stale_query, refresh)

        lookup = await cache.get_data(
            cache.overview_data_key("user-1", "1234567890123"),
            now=clock.value,
        )
        assert lookup.entry is not None
        cached = RoleOverview.model_validate(cache.decode_json(lookup.entry.content))
        assert cached.role_name == "刷新概览"
    finally:
        await database.dispose()
