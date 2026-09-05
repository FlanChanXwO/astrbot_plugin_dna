"""Goal 3 / Task 19：轮询事件落盘与 pending 投递的最终回归契约。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateBaseline,
    ClientUpdateChange,
    ClientUpdateDeliveryService,
    ClientUpdateObservation,
    ClientUpdatePendingTarget,
    ClientUpdatePush,
    ClientUpdateService,
    ClientUpdateStateError,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
    messages,
)

UTC_NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


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


def _change(previous: int = 100, current: int = 101) -> ClientUpdateChange:
    return ClientUpdateChange(
        previous=_snapshot(ClientPlatform.PC, previous),
        current=_snapshot(ClientPlatform.PC, current),
        added_size_bytes=current - previous,
        region=ClientRegion.CN,
        platform=ClientPlatform.PC,
    )


class _SequenceTransport:
    def __init__(self) -> None:
        self._responses = {
            ClientPlatform.PC: [
                ClientUpdateObservation(
                    _snapshot(ClientPlatform.PC, 101),
                    patch_sizes={101: 1},
                ),
                ClientUpdateObservation(
                    _snapshot(ClientPlatform.PC, 101),
                    patch_sizes={101: 1},
                ),
            ],
            ClientPlatform.ANDROID: [
                ClientUpdateObservation(_snapshot(ClientPlatform.ANDROID, 200)),
            ],
        }

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        del previous_patch_version
        return self._responses[ClientPlatform(platform)].pop(0)


class _RecordingPushPort:
    def __init__(self) -> None:
        self.pushes: list[ClientUpdatePush] = []

    async def send(self, push: ClientUpdatePush) -> bool:
        self.pushes.append(push)
        return True


async def _add_subscription(
    subscriptions: SubscriptionStore,
    origin: str = "onebot:group:a",
) -> None:
    await subscriptions.add(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin=origin,
        group_id=origin,
        bot_id="onebot",
        extra_data=json.dumps({"platforms": [ClientPlatform.PC.value]}),
        provenance="chat_command",
    )


@pytest.mark.asyncio
async def test_poll_stages_change_atomically_with_baseline_before_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """状态写入失败不能推进基线；成功轮询必须同时留下固定目标事件。"""

    state_path = tmp_path / "client_update_state.json"
    state = ClientUpdateStateStore(state_path)
    await state.save_baseline(
        ClientUpdateBaseline(_snapshot(ClientPlatform.PC, 100), UTC_NOW)
    )
    await state.save_baseline(
        ClientUpdateBaseline(_snapshot(ClientPlatform.ANDROID, 200), UTC_NOW)
    )
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions)
    service = ClientUpdateService(
        state,
        transport=_SequenceTransport(),
        subscriptions=subscriptions,
    )

    original_replace = Path.replace

    def fail_state_replace(self: Path, target: str | Path) -> Path:
        if Path(target) == state_path:
            raise OSError("simulated state replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_state_replace)
    with pytest.raises(ClientUpdateStateError):
        await service.poll_now()

    failed_baseline = await state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert failed_baseline is not None
    assert failed_baseline.snapshot.patch_version == 100
    assert await state.pending_events() == ()

    monkeypatch.undo()
    changes = await service.poll_now()

    assert [change.event_key for change in changes] == ["cn:pc_cn:100:101"]
    pending = await state.pending_events()
    assert len(pending) == 1
    assert pending[0].event_key == "cn:pc_cn:100:101"
    assert [(target.origin, target.uid) for target in pending[0].pending_targets] == [
        ("onebot:group:a", "")
    ]


@pytest.mark.asyncio
async def test_delivery_does_not_repeat_change_already_staged_by_poll(
    tmp_path: Path,
) -> None:
    """pending-first 成功清理事件后，当前轮询结果不能再次创建同一事件。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _add_subscription(subscriptions)
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    change = _change()
    staged = await state.ensure_pending_event(
        change,
        (ClientUpdatePendingTarget(origin="onebot:group:a", bot_id="onebot"),),
    )
    assert staged is not None

    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port, state=state)

    assert await delivery.deliver((change,)) == 1
    assert len(port.pushes) == 1
    assert await state.pending_events() == ()
