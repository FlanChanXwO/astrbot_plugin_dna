"""Goal 3 / Task 21：客户端更新定时轮询到宿主推送的闭环契约。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from astrbot.core.message.components import Nodes, Plain
from astrbot.core.message.message_event_result import MessageChain

from src.infrastructure.client_updates_scheduler import ClientUpdatesScheduler
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.scheduler_state import SchedulerRegistry
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateDeliveryService,
    ClientUpdateObservation,
    ClientUpdatePush,
    ClientUpdatePushAdapter,
    ClientUpdatePushMessage,
    ClientUpdatePushTarget,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)


def _snapshot(platform: ClientPlatform, patch_version: int) -> ClientVersionSnapshot:
    """构造闭环测试所需的最小有效版本快照。"""

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
    platform: ClientPlatform, previous: int, current: int
) -> ClientUpdateChange:
    """构造一个单平台版本变化。"""

    return ClientUpdateChange(
        previous=_snapshot(platform, previous),
        current=_snapshot(platform, current),
        added_size_bytes=10,
        region=ClientRegion.CN,
        platform=platform,
    )


class _SequenceTransport:
    """为 service 提供首次基线和随后变化。"""

    def __init__(self) -> None:
        self._observations = {
            ClientPlatform.PC: [
                ClientUpdateObservation(_snapshot(ClientPlatform.PC, 100)),
                ClientUpdateObservation(
                    _snapshot(ClientPlatform.PC, 101),
                    patch_sizes={101: 10},
                ),
            ],
            ClientPlatform.ANDROID: [
                ClientUpdateObservation(_snapshot(ClientPlatform.ANDROID, 200)),
                ClientUpdateObservation(_snapshot(ClientPlatform.ANDROID, 200)),
            ],
        }

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        normalized = ClientPlatform(platform)
        return self._observations[normalized].pop(0)


class _BlockingSleep:
    """让 scheduler 只执行一轮并在断言前保持可取消。"""

    def __init__(self) -> None:
        self.calls = 0
        self.reached_second_sleep = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, _seconds: float) -> None:
        self.calls += 1
        if self.calls == 1:
            return
        self.reached_second_sleep.set()
        await self.release.wait()


class _ChangeSource:
    """返回一轮变化并等待 scheduler 进入下一轮。"""

    def __init__(self, change: ClientUpdateChange) -> None:
        self.change = change
        self.called = asyncio.Event()

    async def poll_now(self) -> tuple[ClientUpdateChange, ...]:
        self.called.set()
        return (self.change,)


class _RecordingDelivery:
    """记录 scheduler 交给 delivery service 的变化。"""

    def __init__(self) -> None:
        self.calls: list[tuple[ClientUpdateChange, ...]] = []
        self.called = asyncio.Event()

    async def deliver(self, changes: Sequence[ClientUpdateChange]) -> int:
        self.calls.append(tuple(changes))
        self.called.set()
        return 1


class _Context:
    """只实现 bootstrap 推送适配器所需的宿主接口。"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, MessageChain]] = []

    async def send_message(self, origin: str, message_chain: MessageChain) -> bool:
        self.messages.append((origin, message_chain))
        return True


class _UnusedTransport:
    """bootstrap 构造阶段不应主动请求客户端更新接口。"""

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        raise AssertionError(f"unexpected transport call: {platform}")


@pytest.mark.asyncio
async def test_poll_now_returns_platform_changes_for_scheduled_delivery(
    tmp_path: Path,
) -> None:
    """service 轮询结果必须保留每个平台变化，而不只返回计数。"""

    service = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "client_update_state.json"),
        transport=_SequenceTransport(),
    )

    assert await service.poll_now() == ()
    changes = await service.poll_now()

    assert len(changes) == 1
    assert changes[0].platform is ClientPlatform.PC
    assert changes[0].previous.patch_version == 100
    assert changes[0].current.patch_version == 101


@pytest.mark.asyncio
async def test_scheduler_delivers_changes_after_successful_poll(tmp_path: Path) -> None:
    """scheduler 应把轮询得到的变化交给 delivery，并保持独立任务生命周期。"""

    source = _ChangeSource(_change(ClientPlatform.PC, 100, 101))
    delivery = _RecordingDelivery()
    sleep = _BlockingSleep()
    scheduler = ClientUpdatesScheduler(
        source,
        delivery,
        registry=SchedulerRegistry(tmp_path / "scheduler_state.json"),
        sleep=sleep,
    )

    await scheduler.start()
    await delivery.called.wait()

    assert delivery.calls == [(source.change,)]
    assert scheduler.started is True
    await scheduler.stop()


@pytest.mark.asyncio
async def test_bootstrap_injects_real_text_and_optional_onebot_forward_adapter(
    tmp_path: Path,
) -> None:
    """bootstrap 应把宿主 context 发送能力接入普通消息与 OneBot 合并转发。"""

    from src.bootstrap import build_runtime

    context = _Context()
    runtime = build_runtime(
        context,
        {
            "notifications": {
                "client_update_enabled": False,
                "client_update_merge_forward": True,
            }
        },
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
        client_updates_transport=_UnusedTransport(),
    )

    delivery = cast(
        ClientUpdateDeliveryService, runtime.services["client_update_delivery"]
    )
    adapter = cast(
        ClientUpdatePushAdapter, runtime.services["client_update_push_adapter"]
    )
    scheduler = runtime.services["client_updates_scheduler"]

    assert delivery.subscriptions is runtime.services["subscriptions"]
    assert scheduler.delivery is delivery

    normal_push = ClientUpdatePush(
        target=ClientUpdatePushTarget(
            origin="telegram:group:normal",
            bot_id="bot-1",
        ),
        messages=(
            ClientUpdatePushMessage(
                platform=ClientPlatform.PC,
                text="普通客户端更新",
            ),
        ),
    )
    assert await adapter.send(normal_push) is True

    onebot_push = ClientUpdatePush(
        target=ClientUpdatePushTarget(
            origin="aiocqhttp:GroupMessage:group-1",
            bot_id="bot-1",
        ),
        messages=(
            ClientUpdatePushMessage(
                platform=ClientPlatform.PC,
                text="PC 更新",
            ),
            ClientUpdatePushMessage(
                platform=ClientPlatform.ANDROID,
                text="安卓更新",
            ),
        ),
    )
    assert await adapter.send(onebot_push) is True

    assert len(context.messages) == 2
    normal_chain = context.messages[0][1]
    assert isinstance(normal_chain.chain[0], Plain)
    assert normal_chain.chain[0].text == "普通客户端更新"
    forward_chain = context.messages[1][1]
    assert isinstance(forward_chain.chain[0], Nodes)
    assert [node.content[0].text for node in forward_chain.chain[0].nodes] == [
        "PC 更新",
        "安卓更新",
    ]
