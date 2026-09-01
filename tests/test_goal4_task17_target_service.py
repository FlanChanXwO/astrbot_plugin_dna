"""Goal 4 / Task 17：公告目标生命周期与未来公告基线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.target_service import (
    AnnouncementTargetService,
    TargetMutationStatus,
    encode_target_id,
)


class FakeNoticeListTransport:
    def __init__(self, ids: tuple[str, ...] = ("100", "101")) -> None:
        self.ids = ids
        self.calls = 0
        self.fail = False

    async def current_announcement_ids(self) -> tuple[str, ...]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("list failed")
        return self.ids


@pytest.mark.asyncio
async def test_subscribe_creates_enabled_target_and_unsubscribe_removes_it(tmp_path: Path) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    service = AnnouncementTargetService(store, delivery, FakeNoticeListTransport())

    subscribed = await service.subscribe(
        origin="platform:group:g1",
        group_id="g1",
        bot_id="b1",
        user_id="u1",
    )
    assert subscribed.status is TargetMutationStatus.APPLIED
    assert subscribed.subscription is not None
    assert subscribed.subscription.enabled is True

    target_id = encode_target_id(subscribed.subscription)
    removed = await service.unsubscribe(target_id)
    assert removed.status is TargetMutationStatus.APPLIED
    assert await store.list_all() == ()


@pytest.mark.asyncio
async def test_disable_then_enable_baselines_current_ids_only(tmp_path: Path) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    transport = FakeNoticeListTransport()
    service = AnnouncementTargetService(store, delivery, transport)
    created = await service.subscribe(origin="platform:group:g1", group_id="g1", bot_id="b1")
    assert created.subscription is not None
    target_id = encode_target_id(created.subscription)

    assert (await service.disable(target_id)).status is TargetMutationStatus.APPLIED
    disabled = (await store.list_all())[0]
    assert disabled.enabled is False

    assert (await service.enable(target_id)).status is TargetMutationStatus.APPLIED
    enabled = (await store.list_all())[0]
    assert enabled.enabled is True
    records = await delivery.records()
    assert records["100"].delivered_targets == frozenset({"platform:group:g1"})
    assert records["101"].delivered_targets == frozenset({"platform:group:g1"})

    transport.ids = ("101", "102")
    records = await delivery.records()
    assert "102" not in records


@pytest.mark.asyncio
async def test_enable_failure_keeps_target_disabled(tmp_path: Path) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    transport = FakeNoticeListTransport()
    service = AnnouncementTargetService(store, delivery, transport)
    created = await service.subscribe(origin="platform:group:g1", group_id="g1", bot_id="b1")
    assert created.subscription is not None
    target_id = encode_target_id(created.subscription)
    await service.disable(target_id)
    transport.fail = True

    result = await service.enable(target_id)
    assert result.status is TargetMutationStatus.PARTIAL
    assert (await store.list_all())[0].enabled is False


@pytest.mark.asyncio
async def test_delete_removes_target_even_when_delivery_cleanup_fails(tmp_path: Path) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    delivery = AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json")
    service = AnnouncementTargetService(store, delivery, FakeNoticeListTransport())
    created = await service.subscribe(origin="platform:group:g1", group_id="g1", bot_id="b1")
    assert created.subscription is not None
    target_id = encode_target_id(created.subscription)

    original = delivery.remove_target
    async def fail_cleanup(_target: str) -> None:
        raise RuntimeError("cleanup failed")
    delivery.remove_target = fail_cleanup  # type: ignore[method-assign]

    result = await service.delete(target_id)
    assert result.status is TargetMutationStatus.PARTIAL
    assert await store.list_all() == ()
    delivery.remove_target = original  # type: ignore[method-assign]
