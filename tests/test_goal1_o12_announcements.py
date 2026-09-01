"""O12 公告完整正文、图片和缓存契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.entry.event import EventActor
from src.entry.response import (
    ImageResponse,
    MultiImageResponse,
    PlainTextResponse,
    ResponseFactory,
)
from src.infrastructure.cache import CacheManager
from src.infrastructure.config import CacheSettings
from src.infrastructure.http.notices import DnaApiNoticesTransport
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import NoticesRenderer
from src.infrastructure.rendering import notices as notices_rendering
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.notices import messages
from src.modules.notices.contracts import (
    AnnBlock,
    AnnDetail,
    AnnPost,
    AnnSnapshot,
    NoticeRequest,
    NoticesTransportError,
)
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService


@pytest.mark.asyncio
async def test_ann_detail_transport_unwraps_payload_and_keeps_image_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情 transport 解包 postDetail，不能因 URL 没有纯扩展名而丢图。"""

    async def get_detail(_post_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            is_success=True,
            data={
                "postDetail": {
                    "postId": "42",
                    "postTitle": "完整公告",
                    "postContent": [
                        {"contentType": 1, "content": "正文"},
                        {
                            "contentType": 2,
                            "url": "https://cdn.example/assets/cover?token=abc#full",
                        },
                        {
                            "contentType": 2,
                            "url": "https://cdn.example/assets/no-extension",
                        },
                    ],
                },
            },
        )

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_post_detail", get_detail)
    detail = await DnaApiNoticesTransport.__new__(DnaApiNoticesTransport).get_ann_detail("42")

    assert detail.title == "完整公告"
    assert [block.kind for block in detail.blocks] == ["text", "image", "image"]
    assert [block.image_url for block in detail.blocks if block.kind == "image"] == [
        "https://cdn.example/assets/cover?token=abc#full",
        "https://cdn.example/assets/no-extension",
    ]


@pytest.mark.asyncio
async def test_ann_detail_transport_rejects_missing_post_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情没有有效 postContent 时必须显式失败，不能伪造空详情。"""

    async def get_detail(_post_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            is_success=True,
            data={"postDetail": {"postId": "42", "postTitle": "空公告"}},
        )

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_post_detail", get_detail)

    with pytest.raises(NoticesTransportError):
        await DnaApiNoticesTransport.__new__(DnaApiNoticesTransport).get_ann_detail("42")


@pytest.mark.asyncio
async def test_ann_list_transport_fetches_all_pages_without_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公告列表跨页完整返回，不能复用 legacy 的无 TTL 进程缓存。"""

    calls: list[tuple[int, int]] = []

    async def get_page(*, page_index: int, page_size: int) -> SimpleNamespace:
        calls.append((page_index, page_size))
        posts = [
            {"postId": str(index), "postTitle": f"公告 {index}"}
            for index in range((page_index - 1) * page_size + 1, page_index * page_size + 1)
        ]
        if page_index == 2:
            posts = posts[:1]
        return SimpleNamespace(is_success=True, code=200, data={"postList": posts})

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_ann_list_page", get_page)
    snapshot = await DnaApiNoticesTransport.__new__(DnaApiNoticesTransport).get_ann_list()

    assert len(snapshot.posts) == 21
    assert snapshot.posts[-1].post_id == "21"
    assert calls == [(1, 20), (2, 20)]


@pytest.mark.asyncio
async def test_ann_list_transport_treats_repeated_full_page_as_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上游重复返回满页时，列表仍应返回已收集的唯一公告。"""

    calls: list[tuple[int, int]] = []
    page_posts = [
        {"postId": str(index), "postTitle": f"公告 {index}"}
        for index in range(1, 21)
    ]

    async def get_page(*, page_index: int, page_size: int) -> SimpleNamespace:
        calls.append((page_index, page_size))
        return SimpleNamespace(
            is_success=True,
            code=200,
            data={"postList": page_posts, "hasNext": 1},
        )

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_ann_list_page", get_page)
    snapshot = await DnaApiNoticesTransport.__new__(DnaApiNoticesTransport).get_ann_list()

    assert len(snapshot.posts) == 20
    assert snapshot.posts[0].post_id == "1"
    assert snapshot.posts[-1].post_id == "20"
    assert calls == [(1, 20), (2, 20)]


@pytest.mark.asyncio
async def test_ann_service_resolves_detail_beyond_the_twentieth_item(
    tmp_path: Path,
) -> None:
    """公告序号映射必须覆盖完整列表，而不是只允许前 20 条。"""

    database = AsyncDatabase(tmp_path / "announcements.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )

    class Transport:
        def __init__(self) -> None:
            self.detail_ids: list[str] = []

        async def get_ann_list(self) -> AnnSnapshot:
            return AnnSnapshot(
                posts=tuple(
                    AnnPost(post_id=str(index), title=f"公告 {index}")
                    for index in range(1, 22)
                ),
            )

        async def get_ann_detail(self, post_id: str) -> AnnDetail:
            self.detail_ids.append(post_id)
            return AnnDetail(post_id=post_id, title=f"公告 {post_id}", blocks=())

    class Renderer:
        async def render_ann_detail(self, _detail: AnnDetail) -> SimpleNamespace:
            return SimpleNamespace(path=tmp_path / "detail.png")

    transport = Transport()
    service = NoticesService(
        database,
        transport,
        PrivacyService(database),
        Renderer(),
    )
    response = await service.ann(
        NoticeRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"index": "21"},
            text="公告 21",
        ),
    )

    assert isinstance(response, ImageResponse)
    assert transport.detail_ids == ["21"]
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_service_returns_all_detail_pages_in_one_response(
    tmp_path: Path,
) -> None:
    """公告详情分页必须在同一条响应中保留全部图片页。"""

    database = AsyncDatabase(tmp_path / "announcements-multi-page.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )

    class Transport:
        async def get_ann_list(self) -> AnnSnapshot:
            return AnnSnapshot(posts=(AnnPost(post_id="7", title="公告 7"),))

        async def get_ann_detail(self, _post_id: str) -> AnnDetail:
            return AnnDetail(
                post_id="7",
                title="公告 7",
                blocks=(AnnBlock(kind="text", text="正文"),),
            )

    class Renderer:
        async def render_ann_detail(self, _detail: AnnDetail) -> tuple[SimpleNamespace, ...]:
            return (
                SimpleNamespace(path=tmp_path / "detail-1.png"),
                SimpleNamespace(path=tmp_path / "detail-2.png"),
            )

    service = NoticesService(
        database,
        Transport(),
        PrivacyService(database),
        Renderer(),
    )
    response = await service.ann(
        NoticeRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"index": "1"},
            text="公告 1",
        ),
    )

    assert response.__class__.__name__ == "MultiImageResponse"
    assert [str(image.image) for image in response.images] == [
        str(tmp_path / "detail-1.png"),
        str(tmp_path / "detail-2.png"),
    ]
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_detail_render_failure_returns_fixed_manual_text(
    tmp_path: Path,
) -> None:
    """手动详情素材失败时返回固定文案，不发送占位图或上游错误。"""

    database = AsyncDatabase(tmp_path / "announcements-detail-failure.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )

    class Transport:
        async def get_ann_list(self) -> AnnSnapshot:
            return AnnSnapshot(posts=(AnnPost(post_id="7", title="公告 7"),))

        async def get_ann_detail(self, _post_id: str) -> AnnDetail:
            return AnnDetail(
                post_id="7",
                title="公告 7",
                blocks=(AnnBlock(kind="text", text="正文"),),
            )

    class Renderer:
        async def render_ann_detail(self, _detail: AnnDetail) -> SimpleNamespace:
            raise OSError("upstream image is unavailable")

    service = NoticesService(
        database,
        Transport(),
        PrivacyService(database),
        Renderer(),
    )
    response = await service.ann(
        NoticeRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"index": "1"},
            text="公告 1",
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_DETAIL_FAILED
    assert response.need_at is True
    await database.dispose()


def _png(width: int = 1080, height: int = 80) -> bytes:
    from io import BytesIO

    from PIL import Image

    payload = BytesIO()
    Image.new("RGB", (width, height), "navy").save(payload, format="PNG")
    return payload.getvalue()


@pytest.mark.asyncio
async def test_ann_detail_cache_uses_fingerprint_and_only_stores_complete_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公告详情缓存按正文 fingerprint 失效，失败渲染不能留下成功条目。"""

    manager = CacheManager(tmp_path / "cache", CacheSettings())
    renderer = NoticesRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        cache_manager=manager,
    )
    detail = AnnDetail(
        post_id="7",
        title="公告 7",
        blocks=(AnnBlock(kind="text", text="正文"),),
    )
    calls: list[str] = []

    async def draw_detail(*args: object, **kwargs: object) -> bytes:
        del kwargs
        calls.append(str(args[0]))
        return _png()

    monkeypatch.setattr(notices_rendering, "draw_ann_detail_card", draw_detail)
    first = await renderer.render_ann_detail(detail)
    assert isinstance(first, object)
    first_key = renderer.detail_cache_key(detail, page_index=0)
    first_lookup = await manager.get("announcement", first_key)
    assert first_lookup.status == "fresh"

    async def unexpected_render(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        raise AssertionError("完整 fingerprint 命中时不应重新渲染")

    monkeypatch.setattr(notices_rendering, "draw_ann_detail_card", unexpected_render)
    await renderer.render_ann_detail(detail)
    assert calls == ["7"]

    changed = AnnDetail(
        post_id="7",
        title="公告 7（更新）",
        blocks=detail.blocks,
    )
    monkeypatch.setattr(notices_rendering, "draw_ann_detail_card", draw_detail)
    await renderer.render_ann_detail(changed)
    changed_key = renderer.detail_cache_key(changed, page_index=0)
    assert changed_key != first_key
    changed_lookup = await manager.get("announcement", changed_key)
    assert changed_lookup.status == "fresh"
    assert calls == ["7", "7"]

    failed = AnnDetail(
        post_id="7",
        title="公告 7（失败版本）",
        blocks=detail.blocks,
    )
    monkeypatch.setattr(notices_rendering, "draw_ann_detail_card", unexpected_render)
    with pytest.raises(AssertionError):
        await renderer.render_ann_detail(failed)
    failed_lookup = await manager.get(
        "announcement",
        renderer.detail_cache_key(failed, page_index=0),
    )
    assert failed_lookup.status == "miss"


@pytest.mark.asyncio
async def test_ann_source_image_cache_requires_decodable_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公告源图只有下载并完整解码后才写入 announcement 缓存。"""

    manager = CacheManager(tmp_path / "cache", CacheSettings())
    source_url = "https://cdn.example/image?sig=abc#full"
    content = _png(80, 60)
    calls = 0

    async def fetch_source(_url: str) -> bytes:
        nonlocal calls
        calls += 1
        return content

    monkeypatch.setattr(notices_rendering, "_fetch_image_bytes", fetch_source)
    first = await notices_rendering._source_image_content(
        source_url,
        cache_manager=manager,
        kind="detail",
    )
    second = await notices_rendering._source_image_content(
        source_url,
        cache_manager=manager,
        kind="detail",
    )
    assert first == second == content
    assert calls == 1
    lookup = await manager.get(
        "announcement",
        f"ann-source:detail:{source_url}",
        validator=notices_rendering._image_validator,
    )
    assert lookup.status == "fresh"


def test_response_factory_builds_all_announcement_images_in_one_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多页公告响应在框架边界转换成包含全部图片的单条消息链。"""

    monkeypatch.setattr(
        "src.entry.response.AstrImage.fromFileSystem",
        lambda path: ("image", path),
    )

    class Event:
        def chain_result(self, components: object) -> tuple[str, object]:
            return ("chain", components)

    response = MultiImageResponse(
        (
            ImageResponse("/tmp/announcement-1.png", temporary=False),
            ImageResponse("/tmp/announcement-2.png", temporary=False),
        ),
    )
    assert ResponseFactory().build(Event(), response) == (
        "chain",
        [("image", "/tmp/announcement-1.png"), ("image", "/tmp/announcement-2.png")],
    )


def test_ann_list_template_does_not_apply_css_subject_clamp() -> None:
    """公告列表标题不应通过 CSS 行数上限静默丢失内容。"""

    template = Path("src/templates/cards/announcement_list.html.j2").read_text(
        encoding="utf-8",
    )
    assert "-webkit-line-clamp" not in template


@pytest.mark.asyncio
async def test_ann_list_render_failure_returns_fixed_text(tmp_path: Path) -> None:
    """公告列表渲染失败时返回可见失败文案，不把异常泄露到 handler。"""

    database = AsyncDatabase(tmp_path / "announcements-list-failure.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )

    class Transport:
        async def get_ann_list(self) -> AnnSnapshot:
            return AnnSnapshot(posts=(AnnPost(post_id="7", title="公告 7"),))

    class Renderer:
        async def render_ann_list(self, _snapshot: AnnSnapshot) -> SimpleNamespace:
            raise OSError("render failed")

    service = NoticesService(
        database,
        Transport(),
        PrivacyService(database),
        Renderer(),
    )
    response = await service.ann(
        NoticeRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={},
            text="公告",
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_LIST_FAILED
    assert response.need_at is True
    await database.dispose()
