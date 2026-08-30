"""D04-R 通知失败语义、缓存租约和公告详情 manifest 边界。"""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.infrastructure.cache import CacheManager
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import NoticesRenderer, RenderedNoticesImage
from src.infrastructure.rendering.errors import T2IRenderError
from src.infrastructure.resources import EncyclopediaResourceStore
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from src.modules.notices.contracts import AnnBlock, AnnDetail, MhSnapshot, NoticeRequest
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService
from tests.test_notices import FakeNoticesTransport, _mh_snapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Renderer:
    def __init__(self, root: Path) -> None:
        self.path = root / "mh.png"

    async def render_mh(self, _snapshot: MhSnapshot, **_kwargs: object):
        return SimpleNamespace(path=self.path)


async def _database_with_binding(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "d04-r.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )
    return database


def _request(text: str = "密函测试") -> NoticeRequest:
    return NoticeRequest(
        actor=EventActor(
            "user-1",
            "bot-1",
            "group-1",
            unified_msg_origin="platform:group:g1",
        ),
        target_user_id=None,
        text=text,
    )


def _service(
    database: AsyncDatabase,
    transport: FakeNoticesTransport,
    tmp_path: Path,
    *,
    subscriptions: SubscriptionStore,
    push,
    renderer: _Renderer | None = None,
    cache_manager: CacheManager | None = None,
) -> NoticesService:
    return NoticesService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        renderer or _Renderer(tmp_path / "rendered"),
        subscriptions=subscriptions,
        push=push,
        cache_manager=cache_manager,
        clock=lambda: datetime(2026, 8, 30, 12, 35, tzinfo=SHANGHAI),
    )


@pytest.mark.asyncio
async def test_mh_test_push_reports_target_failure(tmp_path: Path) -> None:
    """密函测试目标失败时不能返回成功文案。"""

    database = await _database_with_binding(tmp_path)

    async def push(_origin: str, _payload: object) -> bool:
        return False

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=SubscriptionStore(tmp_path / "subscriptions.json"),
        push=push,
    )

    response = await service.test_mh_push(_request())

    assert response.text == "密函测试发送失败"
    assert response.text != messages.MH_TEST_SENT
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_push_skips_picture_when_rendering_fails_after_text_delivery(
    tmp_path: Path,
) -> None:
    """密函图片渲染失败时保留已成功文本目标，并跳过图片目标。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []

    async def push(origin: str, payload: object) -> None:
        pushed.append((origin, payload))

    cache = CacheManager(tmp_path / "cache")
    service = _service(
        database,
        FakeNoticesTransport(mh=_mh_snapshot()),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
        cache_manager=cache,
    )

    await subscriptions.add(
        messages.MH_TEXT_SUBSCRIBE,
        origin="platform:group:text",
        user_id="user-1",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.MH_PIC_SUBSCRIBE,
        origin="platform:group:pic",
        user_id="user-1",
        bot_id="bot-1",
    )

    async def fail_render(*_args: object, **_kwargs: object):
        raise T2IRenderError("renderer unavailable")

    service.renderer.render_mh = fail_render  # type: ignore[method-assign]

    assert await service.push_mh_now() == 1
    assert [origin for origin, _payload in pushed] == ["platform:group:text"]
    await database.dispose()


@pytest.mark.asyncio
async def test_corrupt_lease_sidecar_does_not_mask_body_failure(tmp_path: Path) -> None:
    """租约释放读取损坏 sidecar 时仍保留调用方原始异常。"""

    manager = CacheManager(tmp_path / "cache")
    await manager.put("player_card", "lease", b"payload")
    _data_path, metadata_path = manager._paths("player_card", "lease")

    with pytest.raises(RuntimeError, match="body failure"):
        async with manager.lease("player_card", "lease"):
            metadata_path.write_text("{", encoding="utf-8")
            raise RuntimeError("body failure")


def _png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1080, 40), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("page_indexes", ([1, 1], [1, 0]))
async def test_invalid_detail_manifest_is_not_used_as_page_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_indexes: list[int],
) -> None:
    """重复或非顺序 manifest 必须丢弃并重新渲染，而不是重复/倒序发送。"""

    import src.infrastructure.rendering.notices as notices_rendering

    manager = CacheManager(tmp_path / "cache")
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
    for page_index, color in enumerate(("red", "blue")):
        await manager.put(
            "announcement",
            renderer.detail_cache_key(detail, page_index=page_index),
            _png_bytes(color),
        )
    await manager.put(
        "announcement",
        renderer.detail_manifest_key(detail),
        json.dumps({"pages": page_indexes}).encode("utf-8"),
    )

    calls = 0

    async def rerender(*_args: object, **_kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        return _png_bytes("green")

    monkeypatch.setattr(notices_rendering, "draw_ann_detail_card", rerender)

    result = await renderer.render_ann_detail(detail)

    assert isinstance(result, RenderedNoticesImage)
    assert calls == 1
