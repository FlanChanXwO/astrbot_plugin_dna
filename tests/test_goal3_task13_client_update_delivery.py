"""Goal 3 / Task 13：客户端更新多目标推送与 OneBot 合并转发 Red 契约。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientVersionSnapshot,
)
from src.modules.client_updates.delivery import (
    ClientUpdateDeliveryService,
    ClientUpdatePush,
    ClientUpdatePushAdapter,
    ClientUpdatePushMessage,
    ClientUpdatePushTarget,
)

CLIENT_UPDATE_SUBSCRIPTION_TYPE = "订阅DNA客户端更新"


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
    platform: ClientPlatform, *, previous: int, current: int
) -> ClientUpdateChange:
    return ClientUpdateChange(
        previous=_snapshot(platform, previous),
        current=_snapshot(platform, current),
        added_size_bytes=current - previous,
        region=ClientRegion.CN,
        platform=platform,
    )


class _RecordingPushPort:
    def __init__(self, *, failed_origins: set[str] | None = None) -> None:
        self.failed_origins = failed_origins or set()
        self.pushes: list[ClientUpdatePush] = []

    async def send(self, push: ClientUpdatePush) -> bool:
        self.pushes.append(push)
        if push.target.origin in self.failed_origins:
            raise ConnectionError("temporary target failure")
        return True


@dataclass
class _RecordingMessageSender:
    text_calls: list[tuple[str, str]]
    forward_calls: list[tuple[str, tuple[str, ...]]]

    async def send_text(self, origin: str, text: str) -> bool:
        self.text_calls.append((origin, text))
        return True

    async def send_forward(self, origin: str, texts: tuple[str, ...]) -> bool:
        self.forward_calls.append((origin, texts))
        return True


def _push(*, bot_id: str = "onebot") -> ClientUpdatePush:
    return ClientUpdatePush(
        target=ClientUpdatePushTarget(
            origin="platform:group:g1",
            bot_id=bot_id,
        ),
        messages=(
            ClientUpdatePushMessage(ClientPlatform.PC, "pc update"),
            ClientUpdatePushMessage(ClientPlatform.ANDROID, "android update"),
        ),
    )


@pytest.mark.asyncio
async def test_delivery_filters_platforms_and_keeps_each_target_independent(
    tmp_path: Path,
) -> None:
    """每个订阅目标只收到其平台筛选，推送 DTO 保留平台独立消息。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin="platform:group:pc",
        bot_id="onebot",
        group_id="pc",
        extra_data=json.dumps({"platforms": [ClientPlatform.PC.value]}),
        provenance="chat_command",
    )
    await subscriptions.add(
        CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin="platform:group:android",
        bot_id="telegram",
        group_id="android",
        extra_data=json.dumps({"platforms": [ClientPlatform.ANDROID.value]}),
        provenance="chat_command",
    )
    await subscriptions.add(
        CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin="platform:group:all",
        bot_id="onebot",
        group_id="all",
        extra_data=json.dumps(
            {"platforms": [ClientPlatform.PC.value, ClientPlatform.ANDROID.value]}
        ),
        provenance="chat_command",
    )

    port = _RecordingPushPort()
    delivery = ClientUpdateDeliveryService(subscriptions, port)

    delivered = await delivery.deliver(
        (
            _change(ClientPlatform.PC, previous=100, current=101),
            _change(ClientPlatform.ANDROID, previous=200, current=201),
        )
    )

    assert delivered == 3
    by_origin = {push.target.origin: push for push in port.pushes}
    assert tuple(
        message.platform for message in by_origin["platform:group:pc"].messages
    ) == (ClientPlatform.PC,)
    assert tuple(
        message.platform for message in by_origin["platform:group:android"].messages
    ) == (ClientPlatform.ANDROID,)
    assert tuple(
        message.platform for message in by_origin["platform:group:all"].messages
    ) == (
        ClientPlatform.PC,
        ClientPlatform.ANDROID,
    )
    assert "国服 PC 客户端更新" in by_origin["platform:group:pc"].messages[0].text
    assert (
        "国服 安卓 客户端更新" in by_origin["platform:group:android"].messages[0].text
    )


@pytest.mark.asyncio
async def test_delivery_isolates_failed_target_and_continues_other_targets(
    tmp_path: Path,
) -> None:
    """一个目标投递失败时，其他目标仍应继续发送并计入成功数。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    for origin in ("platform:group:failed", "platform:group:ok"):
        await subscriptions.add(
            CLIENT_UPDATE_SUBSCRIPTION_TYPE,
            origin=origin,
            bot_id="onebot",
            group_id=origin.rsplit(":", 1)[-1],
            extra_data=json.dumps(
                {"platforms": [ClientPlatform.PC.value]},
            ),
            provenance="chat_command",
        )

    port = _RecordingPushPort(failed_origins={"platform:group:failed"})
    delivery = ClientUpdateDeliveryService(subscriptions, port)

    delivered = await delivery.deliver(
        (_change(ClientPlatform.PC, previous=100, current=101),)
    )

    assert delivered == 1
    assert [push.target.origin for push in port.pushes] == [
        "platform:group:failed",
        "platform:group:ok",
    ]


@pytest.mark.asyncio
async def test_push_adapter_merges_two_platform_messages_for_onebot_by_default() -> (
    None
):
    """OneBot 目标默认开启合并转发，并把同轮平台消息组织成节点内容。"""

    sender = _RecordingMessageSender([], [])
    adapter = ClientUpdatePushAdapter(
        send_text=sender.send_text,
        send_forward=sender.send_forward,
    )

    assert await adapter.send(_push()) is True
    assert sender.forward_calls == [
        (
            "platform:group:g1",
            ("pc update", "android update"),
        )
    ]
    assert sender.text_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bot_id", "merge_forward"),
    (("telegram", True), ("onebot", False)),
)
async def test_push_adapter_does_not_merge_non_onebot_or_disabled_targets(
    bot_id: str,
    merge_forward: bool,
) -> None:
    """非 OneBot 目标或关闭开关时，两个平台分别发送普通消息。"""

    sender = _RecordingMessageSender([], [])
    adapter = ClientUpdatePushAdapter(
        send_text=sender.send_text,
        send_forward=sender.send_forward,
        merge_forward=merge_forward,
    )
    await adapter.send(_push(bot_id=bot_id))

    assert sender.forward_calls == []
    assert sender.text_calls == [
        ("platform:group:g1", "pc update"),
        ("platform:group:g1", "android update"),
    ]


@pytest.mark.asyncio
async def test_push_adapter_falls_back_to_independent_text_when_forward_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """合并转发能力不可用时，必须降级普通消息且不吞掉其他平台内容。"""

    sender = _RecordingMessageSender([], [])

    async def unavailable_forward(_origin: str, _texts: tuple[str, ...]) -> bool:
        raise RuntimeError("forward component unavailable")

    adapter = ClientUpdatePushAdapter(
        send_text=sender.send_text,
        send_forward=unavailable_forward,
    )

    with caplog.at_level(logging.WARNING):
        assert await adapter.send(_push()) is True

    assert "OneBot 合并转发" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "forward component unavailable" not in caplog.text
    assert sender.forward_calls == []
    assert sender.text_calls == [
        ("platform:group:g1", "pc update"),
        ("platform:group:g1", "android update"),
    ]
