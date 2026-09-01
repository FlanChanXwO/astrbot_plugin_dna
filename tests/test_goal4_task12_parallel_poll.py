"""Goal 4 / Task 12：公告内部并行与轮询 single-flight。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.http.concurrency import RequestConcurrencyGate
from src.infrastructure.rendering import notices as rendering
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.ann_state import AnnStateStore
from src.modules.notices.contracts import AnnBlock, AnnDetail, AnnPost, AnnSnapshot
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService
from tests.test_notices_subscriptions import _database_with_binding


@pytest.mark.asyncio
async def test_announcement_list_previews_fetch_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0

    async def load_preview(*_args: object, **_kwargs: object) -> Image.Image:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return Image.new("RGB", (10, 10), "white")

    monkeypatch.setattr(rendering, "_load_preview", load_preview)
    monkeypatch.setattr(
        rendering._RENDERER,
        "render",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=b"ok"),
    )
    posts = [
        {"postId": str(index), "postTitle": f"公告 {index}", "postContent": []}
        for index in range(3)
    ]
    result = await rendering.draw_ann_list_img(posts, strict_previews=True)
    assert result == b"ok"
    assert peak == 3


@pytest.mark.asyncio
async def test_announcement_detail_blocks_fetch_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0

    async def load_detail(*_args: object, **_kwargs: object) -> Image.Image:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return Image.new("RGB", (10, 10), "white")

    monkeypatch.setattr(rendering, "_load_detail_image", load_detail)
    result = await rendering._detail_blocks_payload(
        [("image", "https://img.test/1"), ("image", "https://img.test/2")]
    )
    assert len(result) == 2
    assert peak == 2


@pytest.mark.asyncio
async def test_poll_ann_now_same_wave_shares_one_poll(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.ANN_SUBSCRIBE,
        origin="platform:group:g1",
        user_id="u1",
        bot_id="b1",
    )
    list_started = asyncio.Event()
    release = asyncio.Event()
    list_calls = 0

    class Transport:
        async def get_ann_list(self) -> AnnSnapshot:
            nonlocal list_calls
            list_calls += 1
            list_started.set()
            await release.wait()
            return AnnSnapshot(
                posts=(AnnPost(post_id="1001", title="公告", time="", preview=""),)
            )

        async def get_ann_detail(self, post_id: str) -> AnnDetail:
            return AnnDetail(
                post_id=post_id,
                title="公告",
                blocks=(AnnBlock(kind="text", text="正文"),),
            )

    class Renderer:
        async def render_ann_detail(self, _detail: AnnDetail):
            return SimpleNamespace(path=tmp_path / "detail.jpg")

    pushed: list[str] = []

    async def push(origin: str, _payload: object) -> None:
        pushed.append(origin)

    service = NoticesService(
        database,
        Transport(),  # type: ignore[arg-type]
        PrivacyService(database),
        Renderer(),  # type: ignore[arg-type]
        subscriptions=subscriptions,
        ann_state=AnnStateStore(tmp_path / "ann_state.json"),
        ann_delivery_state=AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json"),
        push=push,
        request_gate=RequestConcurrencyGate(4),
    )
    first = asyncio.create_task(service.poll_ann_now())
    await list_started.wait()
    second = asyncio.create_task(service.poll_ann_now())
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [1, 1]
    assert list_calls == 1
    assert pushed == ["platform:group:g1"]
    await database.dispose()
