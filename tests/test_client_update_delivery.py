"""客户端更新 Target 快照路由与 pending 投递测试。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    ClientSourceVersion,
    ClientUpdateChange,
    ClientUpdateDeliveryService,
    ClientUpdatePush,
    ClientUpdatePushAdapter,
    ClientUpdatePushMessage,
    ClientUpdatePushTarget,
    ClientUpdateRequest,
    ClientUpdateService,
    ClientUpdateStateStore,
    messages,
)


def _change(
    source_id: str,
    target_ids: tuple[str, ...],
    *,
    previous: str = "100",
    current: str = "101",
) -> ClientUpdateChange:
    return ClientUpdateChange(
        previous=ClientSourceVersion(
            source_id=source_id,
            version_text=f"version-{previous}",
            revision_id=previous,
            order_key=int(previous),
        ),
        current=ClientSourceVersion(
            source_id=source_id,
            version_text=f"version-{current}",
            revision_id=current,
            order_key=int(current),
        ),
        history_complete=True,
        added_size_bytes=1024,
        target_ids=target_ids,
    )


def _pc_change(*, previous: str = "100", current: str = "101") -> ClientUpdateChange:
    return _change(
        "cn-official-pc-manifest",
        ("cn-official-pc",),
        previous=previous,
        current=current,
    )


def _ios_change(*, previous: str = "1", current: str = "2") -> ClientUpdateChange:
    return _change(
        "cn-official-ios-app-store",
        ("cn-official-ios",),
        previous=previous,
        current=current,
    )


@dataclass
class _RecordingPushPort:
    results_by_origin: dict[str, list[bool]] = field(default_factory=dict)
    pushes: list[ClientUpdatePush] = field(default_factory=list)

    async def send(self, push: ClientUpdatePush) -> bool:
        self.pushes.append(push)
        results = self.results_by_origin.get(push.target.origin)
        if results:
            return results.pop(0)
        return True


async def _add_subscription(
    subscriptions: SubscriptionStore,
    origin: str,
    *,
    bot_id: str = "bot-1",
    extra_data: str = "{}",
) -> None:
    await subscriptions.add(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin=origin,
        bot_id=bot_id,
        extra_data=extra_data,
    )


def _group_actor(origin: str = "group:1") -> EventActor:
    return EventActor(
        user_id="admin-1",
        group_id="1",
        bot_id="bot-1",
        unified_msg_origin=origin,
    )


@pytest.mark.asyncio
async def test_target_neutral_subscription_receives_source_message(tmp_path) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    port = _RecordingPushPort()
    await _add_subscription(subscriptions, "group:1")
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    delivered = await delivery.deliver((_pc_change(),))

    assert delivered == 1
    assert await state.pending_events() == ()
    assert len(port.pushes) == 1
    assert port.pushes[0].target.origin == "group:1"
    assert port.pushes[0].messages[0].source_id == "cn-official-pc-manifest"
    assert port.pushes[0].messages[0].target_ids == ("cn-official-pc",)
    assert "国服官服 PC" in port.pushes[0].messages[0].text


@pytest.mark.asyncio
async def test_pending_retry_keeps_event_target_snapshot_across_reload(
    tmp_path,
) -> None:
    subscription_path = tmp_path / "subscriptions.json"
    state_path = tmp_path / "client_updates.json"
    subscriptions = SubscriptionStore(subscription_path)
    await _add_subscription(subscriptions, "group:1")
    first_port = _RecordingPushPort({"group:1": [False]})
    first_delivery = ClientUpdateDeliveryService(
        subscriptions,
        first_port,
        state=ClientUpdateStateStore(state_path),
    )

    assert await first_delivery.deliver((_pc_change(),)) == 0
    pending = await ClientUpdateStateStore(state_path).pending_events()
    assert len(pending) == 1
    assert pending[0].change.target_ids == ("cn-official-pc",)
    assert pending[0].pending_targets[0].target_ids == ("cn-official-pc",)

    reloaded_service = ClientUpdateService(
        ClientUpdateStateStore(state_path),
        subscriptions=SubscriptionStore(subscription_path),
        target_ids=("cn-official-ios",),
    )
    await reloaded_service.initialize()
    assert reloaded_service.target_ids == ("cn-official-ios",)

    reloaded_port = _RecordingPushPort()
    reloaded_delivery = ClientUpdateDeliveryService(
        SubscriptionStore(subscription_path),
        reloaded_port,
        state=ClientUpdateStateStore(state_path),
    )

    assert await reloaded_delivery.deliver(()) == 1
    assert await ClientUpdateStateStore(state_path).pending_events() == ()
    assert reloaded_port.pushes[0].messages[0].target_ids == ("cn-official-pc",)
    assert "国服官服 PC" in reloaded_port.pushes[0].messages[0].text
    assert "iOS" not in reloaded_port.pushes[0].messages[0].text


@pytest.mark.asyncio
async def test_unsubscribe_then_resubscribe_does_not_redeliver_old_event(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    failed_port = _RecordingPushPort({"group:1": [False]})
    await _add_subscription(subscriptions, "group:1")
    delivery = ClientUpdateDeliveryService(subscriptions, failed_port, state=state)

    assert await delivery.deliver((_pc_change(),)) == 0
    assert len(await state.pending_events()) == 1

    service = ClientUpdateService(state, subscriptions=subscriptions)
    request = ClientUpdateRequest(actor=_group_actor())
    assert (
        await service.unsubscribe(request)
    ).text == messages.CLIENT_UPDATE_UNSUBSCRIBED
    assert await state.pending_events() == ()
    await service.subscribe(request)

    retry_port = _RecordingPushPort()
    retry_delivery = ClientUpdateDeliveryService(
        subscriptions,
        retry_port,
        state=state,
    )
    assert await retry_delivery.deliver(()) == 0
    assert retry_port.pushes == []


@pytest.mark.asyncio
async def test_only_failed_subscription_target_remains_pending_and_is_retried(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(subscriptions, "group:failed")
    await _add_subscription(subscriptions, "group:success")
    port = _RecordingPushPort(
        {
            "group:failed": [False, True],
            "group:success": [True],
        }
    )
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    assert await delivery.deliver((_pc_change(),)) == 1
    pending = await state.pending_events()
    assert len(pending) == 1
    assert tuple(target.origin for target in pending[0].pending_targets) == (
        "group:failed",
    )

    assert await delivery.deliver(()) == 1
    assert await state.pending_events() == ()
    assert [push.target.origin for push in port.pushes] == [
        "group:failed",
        "group:success",
        "group:failed",
    ]


@pytest.mark.asyncio
async def test_invalid_subscription_metadata_never_receives_or_keeps_pending(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(
        subscriptions,
        "group:invalid",
        extra_data='{"targets":["cn-official-pc"]}',
    )
    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    with caplog.at_level("WARNING"):
        assert await delivery.deliver((_pc_change(),)) == 0

    assert port.pushes == []
    assert await state.pending_events() == ()
    assert "订阅元数据无效，跳过投递" in caplog.text


@pytest.mark.asyncio
async def test_source_messages_use_registry_order_instead_of_change_platform(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions, "group:1")
    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port)

    assert await delivery.deliver((_ios_change(), _pc_change())) == 1

    assert [message.source_id for message in port.pushes[0].messages] == [
        "cn-official-pc-manifest",
        "cn-official-ios-app-store",
    ]
    assert [message.target_ids for message in port.pushes[0].messages] == [
        ("cn-official-pc",),
        ("cn-official-ios",),
    ]


@pytest.mark.asyncio
async def test_onebot_merge_failure_falls_back_to_independent_source_messages() -> None:
    forward_calls: list[tuple[str, tuple[str, ...]]] = []
    text_calls: list[tuple[str, str]] = []

    async def send_forward(origin: str, texts: tuple[str, ...]) -> bool:
        forward_calls.append((origin, texts))
        return False

    async def send_text(origin: str, text: str) -> bool:
        text_calls.append((origin, text))
        return True

    adapter = ClientUpdatePushAdapter(
        send_text=send_text,
        send_forward=send_forward,
        merge_forward=True,
    )
    push = ClientUpdatePush(
        target=ClientUpdatePushTarget(origin="onebot:group:1", bot_id="onebot"),
        messages=(
            ClientUpdatePushMessage(
                source_id="cn-official-pc-manifest",
                target_ids=("cn-official-pc",),
                text="PC update",
            ),
            ClientUpdatePushMessage(
                source_id="cn-official-ios-app-store",
                target_ids=("cn-official-ios",),
                text="iOS update",
            ),
        ),
    )

    assert await adapter.send(push) is True
    assert forward_calls == [
        ("onebot:group:1", ("PC update", "iOS update")),
    ]
    assert text_calls == [
        ("onebot:group:1", "PC update"),
        ("onebot:group:1", "iOS update"),
    ]
