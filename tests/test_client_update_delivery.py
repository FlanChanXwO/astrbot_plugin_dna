"""客户端更新 Target 快照路由与 pending 投递测试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    AppStoreProviderConfig,
    ClientPlatform,
    ClientSourceVersion,
    ClientUpdateChange,
    ClientUpdateDeliveryService,
    ClientUpdateProviderKind,
    ClientUpdatePush,
    ClientUpdatePushAdapter,
    ClientUpdatePushMessage,
    ClientUpdatePushResult,
    ClientUpdatePushTarget,
    ClientUpdateRegistry,
    ClientUpdateRequest,
    ClientUpdateService,
    ClientUpdateSource,
    ClientUpdateStateStore,
    ClientUpdateTarget,
    messages,
)


def _shared_source_registry() -> ClientUpdateRegistry:
    source = ClientUpdateSource(
        source_id="shared-source",
        platform=ClientPlatform.IOS,
        provider_kind=ClientUpdateProviderKind.APP_STORE,
        provider_config=AppStoreProviderConfig(track_id=1, country="cn"),
    )
    return ClientUpdateRegistry(
        sources=(source,),
        targets=(
            ClientUpdateTarget(
                target_id="cn-official-ios",
                region_id="cn",
                ecosystem_id="official",
                platform=ClientPlatform.IOS,
                source_id=source.source_id,
                display_name="国服官服 iOS",
            ),
            ClientUpdateTarget(
                target_id="global-official-ios",
                region_id="global",
                ecosystem_id="official",
                platform=ClientPlatform.IOS,
                source_id=source.source_id,
                display_name="全球服官服 iOS",
            ),
        ),
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

    async def send(self, push: ClientUpdatePush) -> ClientUpdatePushResult:
        self.pushes.append(push)
        results = self.results_by_origin.get(push.target.origin)
        succeeded = results.pop(0) if results else True
        return ClientUpdatePushResult(
            succeeded_event_keys=tuple(
                message.event_key for message in push.messages if succeeded
            )
        )


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


def test_delivery_requires_state_dependency(tmp_path) -> None:
    """state 是唯一的生产投递语义，未注入时必须拒绝构造。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    port = _RecordingPushPort()

    with pytest.raises(TypeError):
        # 生产不存在无状态投递路径，构造期即应暴露缺失依赖。
        ClientUpdateDeliveryService(subscriptions, port)  # type: ignore[call-arg]


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
async def test_delivery_uses_the_injected_registry_for_custom_sources(tmp_path) -> None:
    registry = _shared_source_registry()
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions, "group:1")
    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(
        subscriptions,
        port,
        state=ClientUpdateStateStore(
            tmp_path / "client_updates.json",
            registry=registry,
        ),
    )

    delivered = await delivery.deliver(
        (
            _change(
                "shared-source",
                ("cn-official-ios", "global-official-ios"),
                previous="1",
                current="2",
            ),
        )
    )

    assert delivered == 1
    assert port.pushes[0].messages[0].source_id == "shared-source"
    assert port.pushes[0].messages[0].target_ids == (
        "cn-official-ios",
        "global-official-ios",
    )


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
async def test_pending_retry_uses_current_subscription_bot_id(tmp_path) -> None:
    subscription_path = tmp_path / "subscriptions.json"
    state_path = tmp_path / "client_updates.json"
    subscriptions = SubscriptionStore(subscription_path)
    await _add_subscription(subscriptions, "group:1", bot_id="old-bot")
    first_port = _RecordingPushPort({"group:1": [False]})
    first_delivery = ClientUpdateDeliveryService(
        subscriptions,
        first_port,
        state=ClientUpdateStateStore(state_path),
    )
    assert await first_delivery.deliver((_pc_change(),)) == 0

    await _add_subscription(subscriptions, "group:1", bot_id="onebot")
    retry_port = _RecordingPushPort()
    retry_delivery = ClientUpdateDeliveryService(
        subscriptions,
        retry_port,
        state=ClientUpdateStateStore(state_path),
    )

    assert await retry_delivery.deliver(()) == 1
    assert retry_port.pushes[0].target.bot_id == "onebot"


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
@pytest.mark.parametrize(
    "extra_data",
    (
        '{"targets":["cn-official-pc"]}',
        '{"platforms":[]}',
        '{"platforms":["ios"]}',
        '{"platforms":["invalid"]}',
        '{"platforms":[1]}',
        "{",
        "[]",
    ),
)
async def test_invalid_subscription_metadata_never_receives_or_keeps_pending(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    extra_data: str,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(
        subscriptions,
        "group:invalid",
        extra_data=extra_data,
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
    delivery = ClientUpdateDeliveryService(
        subscriptions,
        port,
        state=ClientUpdateStateStore(tmp_path / "client_updates.json"),
    )

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
                event_key="cn-official-pc-manifest:100:101",
                source_id="cn-official-pc-manifest",
                target_ids=("cn-official-pc",),
                text="PC update",
            ),
            ClientUpdatePushMessage(
                event_key="cn-official-ios-app-store:1:2",
                source_id="cn-official-ios-app-store",
                target_ids=("cn-official-ios",),
                text="iOS update",
            ),
        ),
    )

    result = await adapter.send(push)
    assert result.succeeded_event_keys == tuple(
        message.event_key for message in push.messages
    )
    assert forward_calls == [
        ("onebot:group:1", ("PC update", "iOS update")),
    ]
    assert text_calls == [
        ("onebot:group:1", "PC update"),
        ("onebot:group:1", "iOS update"),
    ]


@pytest.mark.asyncio
async def test_concurrent_deliveries_do_not_send_the_same_pending_event_twice(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(subscriptions, "group:1")
    seed_delivery = ClientUpdateDeliveryService(
        subscriptions,
        _RecordingPushPort({"group:1": [False]}),
        state=state,
    )
    assert await seed_delivery.deliver((_pc_change(),)) == 0

    started = asyncio.Event()
    release = asyncio.Event()

    @dataclass
    class BlockingPushPort:
        pushes: list[ClientUpdatePush] = field(default_factory=list)

        async def send(self, push: ClientUpdatePush) -> ClientUpdatePushResult:
            self.pushes.append(push)
            if len(self.pushes) == 1:
                started.set()
                await release.wait()
            return ClientUpdatePushResult(
                succeeded_event_keys=tuple(
                    message.event_key for message in push.messages
                )
            )

    port = BlockingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)
    first = asyncio.create_task(delivery.deliver(()))
    await started.wait()
    second = asyncio.create_task(delivery.deliver(()))
    await asyncio.sleep(0)

    assert len(port.pushes) == 1

    release.set()
    assert await asyncio.gather(first, second) == [1, 0]
    assert len(port.pushes) == 1
    assert await state.pending_events() == ()


@pytest.mark.asyncio
async def test_unsubscribe_waits_for_grouped_delivery_before_returning(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(subscriptions, "group:1")
    seed_delivery = ClientUpdateDeliveryService(
        subscriptions,
        _RecordingPushPort({"group:1": [False]}),
        state=state,
    )
    assert await seed_delivery.deliver((_pc_change(),)) == 0

    order: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingPushPort:
        def __init__(self) -> None:
            self.pushes: list[ClientUpdatePush] = []

        async def send(self, push: ClientUpdatePush) -> ClientUpdatePushResult:
            self.pushes.append(push)
            started.set()
            await release.wait()
            order.append("send")
            return ClientUpdatePushResult(
                succeeded_event_keys=tuple(
                    message.event_key for message in push.messages
                )
            )

    port = BlockingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)
    service = ClientUpdateService(state, subscriptions=subscriptions)
    delivery_task = asyncio.create_task(delivery.deliver(()))
    await started.wait()

    async def unsubscribe():
        response = await service.unsubscribe(ClientUpdateRequest(actor=_group_actor()))
        order.append("unsubscribe")
        return response

    unsubscribe_task = asyncio.create_task(unsubscribe())
    await asyncio.sleep(0)
    assert not unsubscribe_task.done()

    release.set()
    delivered, response = await asyncio.gather(delivery_task, unsubscribe_task)

    assert delivered == 1
    assert response.text == messages.CLIENT_UPDATE_UNSUBSCRIBED
    assert order == ["send", "unsubscribe"]
    assert len(port.pushes) == 1
    assert await state.pending_events() == ()
    assert await delivery.deliver(()) == 0


@pytest.mark.asyncio
async def test_partial_text_success_marks_only_successful_event_and_retries_failure(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await _add_subscription(subscriptions, "group:1")
    send_results = [True, False, True]
    sent_texts: list[str] = []

    async def send_text(_origin: str, text: str) -> bool:
        sent_texts.append(text)
        return send_results.pop(0)

    delivery = ClientUpdateDeliveryService(
        subscriptions,
        ClientUpdatePushAdapter(send_text=send_text, merge_forward=False),
        state=state,
    )

    assert await delivery.deliver((_pc_change(), _ios_change())) == 0
    pending = await state.pending_events()
    assert tuple(event.change.source_id for event in pending) == (
        "cn-official-ios-app-store",
    )

    assert await delivery.deliver(()) == 1
    assert await state.pending_events() == ()
    assert len(sent_texts) == 3
    assert "国服官服 PC" in sent_texts[0]
    assert "国服官服 iOS" in sent_texts[1]
    assert "国服官服 iOS" in sent_texts[2]


@pytest.mark.asyncio
async def test_onebot_forward_success_confirms_every_event_without_text_fallback() -> (
    None
):
    forward_calls: list[tuple[str, tuple[str, ...]]] = []
    text_calls: list[tuple[str, str]] = []

    async def send_forward(origin: str, texts: tuple[str, ...]) -> bool:
        forward_calls.append((origin, texts))
        return True

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
                event_key="cn-official-pc-manifest:100:101",
                source_id="cn-official-pc-manifest",
                target_ids=("cn-official-pc",),
                text="PC update",
            ),
            ClientUpdatePushMessage(
                event_key="cn-official-ios-app-store:1:2",
                source_id="cn-official-ios-app-store",
                target_ids=("cn-official-ios",),
                text="iOS update",
            ),
        ),
    )

    result = await adapter.send(push)

    assert result.succeeded_event_keys == tuple(
        message.event_key for message in push.messages
    )
    assert forward_calls == [
        ("onebot:group:1", ("PC update", "iOS update")),
    ]
    assert text_calls == []


@pytest.mark.asyncio
async def test_onebot_forward_exception_reports_each_text_result() -> None:
    text_results = [True, False]

    async def send_forward(_origin: str, _texts: tuple[str, ...]) -> bool:
        raise RuntimeError("forward unavailable")

    async def send_text(_origin: str, _text: str) -> bool:
        return text_results.pop(0)

    adapter = ClientUpdatePushAdapter(
        send_text=send_text,
        send_forward=send_forward,
        merge_forward=True,
    )
    push = ClientUpdatePush(
        target=ClientUpdatePushTarget(origin="onebot:group:1", bot_id="onebot"),
        messages=(
            ClientUpdatePushMessage(
                event_key="cn-official-pc-manifest:100:101",
                source_id="cn-official-pc-manifest",
                target_ids=("cn-official-pc",),
                text="PC update",
            ),
            ClientUpdatePushMessage(
                event_key="cn-official-ios-app-store:1:2",
                source_id="cn-official-ios-app-store",
                target_ids=("cn-official-ios",),
                text="iOS update",
            ),
        ),
    )

    result = await adapter.send(push)

    assert result.succeeded_event_keys == ("cn-official-pc-manifest:100:101",)
