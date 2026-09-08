"""Goal 4 / Task 20：公告目标跨重启与投递一致性。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.ann_state import AnnStateStore
from src.modules.notices.contracts import AnnBlock, AnnDetail, AnnPost, AnnSnapshot
from src.modules.notices.target_service import (
    AnnouncementTargetService,
    encode_target_id,
)
from tests.test_notices_subscriptions import _database_with_binding, _service


class MutableAnnouncementTransport:
    def __init__(self, ids: tuple[str, ...]) -> None:
        self.ids = ids

    async def current_announcement_ids(self) -> tuple[str, ...]:
        return self.ids

    async def get_ann_list(self) -> AnnSnapshot:
        return AnnSnapshot(
            tuple(AnnPost(post_id=item, title=f"公告 {item}") for item in self.ids)
        )

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        return AnnDetail(
            post_id=post_id,
            title=f"公告 {post_id}",
            blocks=(AnnBlock(kind="text", text="正文"),),
        )


class Renderer:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def render_ann_detail(self, detail: AnnDetail):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{detail.post_id}.jpg"
        path.write_bytes(b"rendered")
        return SimpleNamespace(path=path)


def build_runtime(database, tmp_path: Path, transport, pushed, *, fail=()):
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    targets = AnnouncementTargetService(subscriptions, delivery, transport)

    async def push(origin: str, _payload: object) -> None:
        if origin in fail:
            raise ConnectionError("temporary failure")
        pushed.append(origin)

    notices = _service(
        database, transport, tmp_path, subscriptions=subscriptions, push=push
    )
    notices.ann_delivery_state = delivery
    notices.ann_state = AnnStateStore(tmp_path / "ann_state.json")
    notices.renderer = Renderer(tmp_path / "rendered")
    notices.announcement_targets = targets
    return subscriptions, targets, notices


@pytest.mark.asyncio
async def test_disable_enable_delete_survive_restart_without_backfill(
    tmp_path: Path,
) -> None:
    database = await _database_with_binding(tmp_path)
    transport = MutableAnnouncementTransport(("1001",))
    pushed: list[str] = []
    _store, targets, _notices = build_runtime(database, tmp_path, transport, pushed)
    created = await targets.subscribe(
        origin="platform:group:g1", group_id="g1", bot_id="b1"
    )
    assert created.subscription is not None
    target_id = encode_target_id(created.subscription)

    await targets.disable(target_id)
    _store, targets, notices = build_runtime(database, tmp_path, transport, pushed)
    assert await notices.poll_ann_now() == 0
    assert pushed == []

    await targets.enable(target_id)
    _store, targets, notices = build_runtime(database, tmp_path, transport, pushed)
    assert await notices.poll_ann_now() == 0
    assert pushed == []

    transport.ids = ("1001", "1002")
    assert await notices.poll_ann_now() == 1
    assert pushed == ["platform:group:g1"]

    await targets.delete(target_id)
    transport.ids = ("1001", "1002", "1003")
    _store, _targets, notices = build_runtime(database, tmp_path, transport, pushed)
    assert await notices.poll_ann_now() == 0
    assert pushed == ["platform:group:g1"]
    await database.dispose()


@pytest.mark.asyncio
async def test_restart_retries_only_failed_announcement_target(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    transport = MutableAnnouncementTransport(("2001",))
    pushed: list[str] = []
    _store, targets, _notices = build_runtime(database, tmp_path, transport, pushed)
    await targets.subscribe(origin="platform:group:ok", group_id="ok", bot_id="b1")
    await targets.subscribe(origin="platform:group:fail", group_id="fail", bot_id="b1")

    _store, _targets, notices = build_runtime(
        database,
        tmp_path,
        transport,
        pushed,
        fail={"platform:group:fail"},
    )
    assert await notices.poll_ann_now() == 1
    assert pushed == ["platform:group:ok"]

    _store, _targets, notices = build_runtime(database, tmp_path, transport, pushed)
    assert await notices.poll_ann_now() == 1
    assert pushed == ["platform:group:ok", "platform:group:fail"]
    await database.dispose()
