"""Goal 3 / Task 22：客户端更新 pending 投递状态与重试 Red 契约。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateDeliveryService,
    ClientUpdatePendingEvent,
    ClientUpdatePendingTarget,
    ClientUpdateStateError,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
    messages,
)

UTC_ISO = "2026-09-02T01:00:00+00:00"


def _snapshot(platform: ClientPlatform, patch_version: int) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
        platform=platform,
        region=ClientRegion.CN,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=(
            str(patch_version) if platform is ClientPlatform.ANDROID else None
        ),
        major=1,
        minor=5,
        revamp=192,
        patch_key=patch_version,
    )


def _change(
    platform: ClientPlatform = ClientPlatform.PC,
    *,
    previous: int = 100,
    current: int = 101,
) -> ClientUpdateChange:
    return ClientUpdateChange(
        previous=_snapshot(platform, previous),
        current=_snapshot(platform, current),
        added_size_bytes=current - previous,
        region=ClientRegion.CN,
        platform=platform,
    )


def _target(origin: str, *, bot_id: str = "onebot", uid: str = ""):
    return ClientUpdatePendingTarget(origin=origin, uid=uid, bot_id=bot_id)


class _RecordingPushPort:
    def __init__(self, failed_origins: set[str] | None = None) -> None:
        self.failed_origins = failed_origins or set()
        self.pushes = []

    async def send(self, push):
        self.pushes.append(push)
        return push.target.origin not in self.failed_origins


async def _add_subscription(
    subscriptions: SubscriptionStore,
    origin: str,
    *,
    platforms: tuple[ClientPlatform, ...] = (ClientPlatform.PC,),
    bot_id: str = "onebot",
) -> None:
    await subscriptions.add(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin=origin,
        bot_id=bot_id,
        group_id=origin,
        extra_data=json.dumps({"platforms": [item.value for item in platforms]}),
        provenance="chat_command",
    )


@pytest.mark.asyncio
async def test_pending_event_persists_fixed_targets_and_reloads(tmp_path: Path) -> None:
    """事件键、变化快照和首次目标集合必须跨进程重载。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    change = _change()

    created = await store.ensure_pending_event(
        change,
        (_target("onebot:group:a"), _target("telegram:group:b", bot_id="telegram")),
    )

    assert isinstance(created, ClientUpdatePendingEvent)
    assert created.event_key == "cn:pc:100:101"
    assert [target.origin for target in created.pending_targets] == [
        "onebot:group:a",
        "telegram:group:b",
    ]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["pending_events"][0]["event_key"] == created.event_key
    assert {target["status"] for target in raw["pending_events"][0]["targets"]} == {
        "pending"
    }

    reloaded = ClientUpdateStateStore(path)
    events = await reloaded.pending_events()
    assert events == (created,)
    assert events[0].change == change


@pytest.mark.asyncio
async def test_legacy_baseline_state_is_migrated_without_losing_baselines(
    tmp_path: Path,
) -> None:
    """旧版仅含基线的状态可读入，并在首次加载时升级 schema。"""

    path = tmp_path / "client_update_state.json"
    path.write_text(
        json.dumps({"schema_version": 1, "baselines": {}}),
        encoding="utf-8",
    )
    store = ClientUpdateStateStore(path)
    assert await store.pending_events() == ()

    from src.modules.client_updates import ClientUpdateBaseline

    await store.save_baseline(
        ClientUpdateBaseline(
            snapshot=_snapshot(ClientPlatform.PC, 100),
            observed_at=datetime.fromisoformat(UTC_ISO),
        )
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 3
    assert raw["pending_events"] == []


@pytest.mark.asyncio
async def test_scheduled_delivery_retries_pending_before_new_and_excludes_new_target(
    tmp_path: Path,
) -> None:
    """失败事件先重试；事件生成后的新订阅者不接收历史变化。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(
        subscriptions,
        "onebot:group:a",
        platforms=(ClientPlatform.PC, ClientPlatform.ANDROID),
    )
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    port = _RecordingPushPort({"onebot:group:a"})
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    first_change = _change(ClientPlatform.PC, previous=100, current=101)
    assert await delivery.deliver((first_change,)) == 0
    assert [push.target.origin for push in port.pushes] == ["onebot:group:a"]

    await _add_subscription(
        subscriptions,
        "onebot:group:b",
        platforms=(ClientPlatform.PC, ClientPlatform.ANDROID),
    )
    port.failed_origins.clear()

    second_change = _change(ClientPlatform.ANDROID, previous=200, current=201)
    assert await delivery.deliver((second_change,)) == 3

    assert [push.target.origin for push in port.pushes] == [
        "onebot:group:a",
        "onebot:group:a",
        "onebot:group:a",
        "onebot:group:b",
    ]
    assert [push.messages[0].platform for push in port.pushes] == [
        ClientPlatform.PC,
        ClientPlatform.PC,
        ClientPlatform.ANDROID,
        ClientPlatform.ANDROID,
    ]
    assert await state.pending_events() == ()


@pytest.mark.asyncio
async def test_pending_write_failure_restores_previous_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """待投递状态写盘失败时显式报错且不提交内存事件。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    first = await store.ensure_pending_event(
        _change(),
        (_target("onebot:group:a"),),
    )
    assert first is not None
    previous_bytes = path.read_bytes()
    original_replace = Path.replace

    def fail_final_replace(self: Path, target: str | Path) -> Path:
        if Path(target) == path:
            raise OSError("simulated state replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_final_replace)

    with pytest.raises(ClientUpdateStateError):
        await store.ensure_pending_event(
            _change(previous=101, current=102),
            (_target("onebot:group:a"),),
        )

    assert path.read_bytes() == previous_bytes
    assert await store.pending_events() == (first,)


@pytest.mark.asyncio
async def test_duplicate_event_key_in_one_delivery_is_sent_once(tmp_path: Path) -> None:
    """同一轮重复输入同一 event_key 时只创建并投递一个事件。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions, "onebot:group:a")
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    change = _change()
    assert await delivery.deliver((change, change)) == 1
    assert len(port.pushes) == 1
    assert [message.platform for message in port.pushes[0].messages] == [
        ClientPlatform.PC
    ]
    assert await state.pending_events() == ()


@pytest.mark.asyncio
async def test_one_target_failure_keeps_only_that_target_pending_across_reload(
    tmp_path: Path,
) -> None:
    """一个目标失败不回滚其他目标，重载后只重试失败目标。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions, "onebot:group:a")
    await _add_subscription(subscriptions, "telegram:group:b", bot_id="telegram")
    path = tmp_path / "client_update_state.json"
    state = ClientUpdateStateStore(path)
    port = _RecordingPushPort({"onebot:group:a"})
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    change = _change()
    assert await delivery.deliver((change,)) == 1
    pending = await state.pending_events()
    assert len(pending) == 1
    assert [(target.origin, target.delivered) for target in pending[0].targets] == [
        ("onebot:group:a", False),
        ("telegram:group:b", True),
    ]

    reloaded = ClientUpdateStateStore(path)
    retry_port = _RecordingPushPort()
    retry_delivery = ClientUpdateDeliveryService(
        subscriptions,
        retry_port,
        state=reloaded,
    )
    assert await retry_delivery.deliver(()) == 1
    assert [push.target.origin for push in retry_port.pushes] == ["onebot:group:a"]
    assert await reloaded.pending_events() == ()


@pytest.mark.asyncio
async def test_removing_last_pending_target_cleans_delivered_only_event(
    tmp_path: Path,
) -> None:
    """剩余目标全为 delivered 时也必须清理事件，避免重载出无 pending 记录。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    event = await store.ensure_pending_event(
        _change(),
        (_target("onebot:group:a"), _target("telegram:group:b", bot_id="telegram")),
    )
    assert event is not None
    assert await store.mark_delivered(event.event_key, ("telegram:group:b", ""))
    assert await store.remove_event_target(event.event_key, ("onebot:group:a", ""))
    assert await store.pending_events() == ()
    assert await ClientUpdateStateStore(path).pending_events() == ()


@pytest.mark.asyncio
async def test_unsubscribe_and_disable_remove_pending_target_without_replay(
    tmp_path: Path,
) -> None:
    """取消或停用目标会清理 pending，重新订阅也不会补发旧事件。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    origin = "onebot:group:a"
    await _add_subscription(subscriptions, origin)
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    port = _RecordingPushPort({origin})
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)
    change = _change()
    await delivery.deliver((change,))

    actor = EventActor(
        user_id="admin",
        bot_id="onebot",
        group_id=origin,
        unified_msg_origin=origin,
    )
    from src.modules.client_updates import ClientUpdateRequest, ClientUpdateService

    service = ClientUpdateService(state, subscriptions=subscriptions)
    response = await service.unsubscribe(ClientUpdateRequest(actor=actor))
    assert response.text == messages.CLIENT_UPDATE_UNSUBSCRIBED
    assert await state.pending_events() == ()

    await _add_subscription(subscriptions, origin)
    port.failed_origins.clear()
    await delivery.deliver(())
    assert len(port.pushes) == 1

    port.failed_origins.add(origin)
    await delivery.deliver((_change(previous=101, current=102),))
    assert len(await state.pending_events()) == 1
    await subscriptions.update(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin,
        enabled=False,
    )
    await delivery.deliver(())
    assert await state.pending_events() == ()
