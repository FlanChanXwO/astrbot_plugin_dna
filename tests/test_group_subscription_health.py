"""Regression tests for unreachable group subscription cleanup."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.subscriptions.group_probe import probe_group_membership
from src.infrastructure.subscriptions.store import SubscriptionStore
from src.modules.client_updates import (
    ClientSourceVersion,
    ClientUpdateBaseline,
    ClientUpdateChange,
    ClientUpdatePendingTarget,
    ClientUpdateStateStore,
    ManifestCdnVersionMetadata,
)
from src.modules.group_subscription_health import (
    GroupSubscriptionHealth,
    group_key,
)
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore


def test_group_identity_handles_telegram_topics_and_excludes_private_chat():
    assert group_key("telegram-main:GroupMessage:-100123#42") == (
        "telegram-main",
        "-100123",
    )
    assert group_key("主ob11:GroupMessage:10012") == ("主ob11", "10012")
    assert group_key("telegram-main:FriendMessage:-100123") is None


def _new_stores(tmp_path: Path):
    return (
        SubscriptionStore(tmp_path / "subscriptions.json"),
        AnnDeliveryStateStore(tmp_path / "announcements.json"),
        ClientUpdateStateStore(tmp_path / "client_update.json"),
    )


def _version(revision: int) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id="cn-official-pc-manifest",
        version_text=f"1.6.{revision}",
        revision_id=str(revision),
        order_key=(revision, revision),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=revision,
            patch_version=revision,
            resource_version_dir=None,
        ),
    )


@pytest.mark.asyncio
async def test_confirmed_absence_removes_all_group_topics_and_pending_state(tmp_path):
    subscriptions, announcements, client_updates = _new_stores(tmp_path)
    topic_1 = "telegram-main:GroupMessage:-10042#2"
    topic_2 = "telegram-main:GroupMessage:-10042#9"
    other_bot = "telegram-alt:GroupMessage:-10042#2"
    other_group = "telegram-main:GroupMessage:-10043#2"
    for sub_type, origin in (
        ("公告", topic_1),
        ("密函", topic_2),
        ("签到", topic_2),
        ("公告", other_bot),
        ("公告", other_group),
    ):
        await subscriptions.add(
            sub_type, origin=origin, group_id=origin.rsplit(":", 1)[-1]
        )
    await announcements.pending_targets(
        "1001", (topic_1, topic_2, other_bot, other_group)
    )
    await announcements.mark_delivered("1001", other_group)

    change = ClientUpdateChange(
        previous=_version(1),
        current=_version(2),
        history_complete=True,
        added_size_bytes=200,
        target_ids=("cn-official-pc",),
    )
    await client_updates.save_baseline_with_pending_event(
        ClientUpdateBaseline(change.current, datetime.now(UTC), change),
        change,
        tuple(
            ClientUpdatePendingTarget(origin=origin)
            for origin in (topic_1, topic_2, other_bot, other_group)
        ),
    )

    probes = []

    async def absent(platform: str, group: str) -> bool:
        probes.append((platform, group))
        return False

    health = GroupSubscriptionHealth(
        subscriptions, announcements, client_updates, absent
    )
    for _ in range(4):
        await health.record(topic_1, False)
    assert len(await subscriptions.list_all()) == 5
    await health.record(topic_1, False)

    assert probes == [("telegram-main", "-10042")]
    assert health.should_skip(topic_2)
    assert {s.unified_msg_origin for s in await subscriptions.list_all()} == {
        other_bot,
        other_group,
    }
    reloaded_ann = AnnDeliveryStateStore(tmp_path / "announcements.json")
    ann = (await reloaded_ann.records())["1001"]
    assert ann.observed_targets == frozenset((other_bot, other_group))
    assert ann.delivered_targets == frozenset((other_group,))
    reloaded_client = ClientUpdateStateStore(tmp_path / "client_update.json")
    events = await reloaded_client.pending_events()
    assert len(events) == 1
    assert {target.origin for target in events[0].targets} == {
        other_bot,
        other_group,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("membership", [None, True])
async def test_transient_failure_or_unknown_membership_preserves_subscriptions(
    tmp_path, membership
):
    subscriptions, announcements, client_updates = _new_stores(tmp_path)
    origin = "qq:GroupMessage:10001"
    await subscriptions.add("公告", origin=origin, group_id="10001")

    async def check(_platform: str, _group: str) -> bool | None:
        return membership

    health = GroupSubscriptionHealth(
        subscriptions, announcements, client_updates, check
    )
    for _ in range(5):
        await health.record(origin, False)
    assert len(await subscriptions.list_all()) == 1
    assert health.should_skip(origin)  # backoff rather than repeated sending
    await health.record(origin, True)
    assert not health.should_skip(origin)


@pytest.mark.asyncio
async def test_success_resets_failure_streak(tmp_path):
    subscriptions, announcements, client_updates = _new_stores(tmp_path)
    calls = []

    async def probe(*args):
        calls.append(args)
        return False

    health = GroupSubscriptionHealth(
        subscriptions, announcements, client_updates, probe
    )
    origin = "qq:GroupMessage:10001"
    for _ in range(4):
        await health.record(origin, False)
    await health.record(origin, True)
    for _ in range(4):
        await health.record(origin, False)
    assert calls == []


class _PlatformContext:
    def __init__(self, kind, client):
        self.platform = SimpleNamespace(
            meta=lambda: SimpleNamespace(name=kind), bot=client, client=client
        )

    def get_platform_inst(self, platform_id):
        return self.platform if platform_id == "one" else None


@pytest.mark.asyncio
async def test_onebot_probe_fails_closed_on_malformed_or_unavailable_group_list():
    class Bot:
        async def call_action(self, action):
            assert action == "get_group_list"
            return [{"group_id": 12345}]

    context = _PlatformContext("aiocqhttp", Bot())
    assert await probe_group_membership(context, "one", "12345") is True
    assert await probe_group_membership(context, "one", "98765") is False
    assert await probe_group_membership(context, "elsewhere", "12345") is None

    class BrokenBot:
        async def call_action(self, _action):
            return {"status": "failed", "data": []}

    assert (
        await probe_group_membership(
            _PlatformContext("aiocqhttp", BrokenBot()), "one", "12345"
        )
        is None
    )


@pytest.mark.asyncio
async def test_telegram_probe_uses_bot_membership_not_topic():
    class Client:
        async def get_me(self):
            return SimpleNamespace(id=987)

        async def get_chat_member(self, chat_id, user_id):
            assert chat_id == -10042
            assert user_id == 987
            return SimpleNamespace(status="kicked")

    assert (
        await probe_group_membership(
            _PlatformContext("telegram", Client()), "one", "-10042"
        )
        is False
    )

    class NetworkError(Exception):
        pass

    class Offline(Client):
        async def get_chat_member(self, chat_id, user_id):
            raise NetworkError("temporarily disconnected")

    assert (
        await probe_group_membership(
            _PlatformContext("telegram", Offline()), "one", "-10042"
        )
        is None
    )
