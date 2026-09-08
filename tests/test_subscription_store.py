"""Task 18 订阅存储的 JSON 持久化与去重测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.checkin import messages

SIGN_RESULT = messages.SIGN_RESULT_SUBSCRIBE


@pytest.mark.asyncio
async def test_subscription_store_add_dedupe_persist_and_reload(tmp_path: Path) -> None:
    """同类型同 origin 只保留最新一条，且写入可重载。"""

    path = tmp_path / "subscriptions.json"
    store = SubscriptionStore(path)

    await store.add(
        SIGN_RESULT,
        origin="platform:group:g1",
        user_id="user-1",
        group_id="group-1",
        bot_id="bot-1",
        user_type="group",
    )
    await store.add(
        SIGN_RESULT,
        origin="platform:group:g1",
        user_id="user-2",
        bot_id="bot-1",
    )

    subs = await store.get(SIGN_RESULT)
    assert len(subs) == 1
    assert subs[0].user_id == "user-2"
    assert subs[0].unified_msg_origin == "platform:group:g1"

    reloaded = SubscriptionStore(path)
    subs = await reloaded.get(SIGN_RESULT)
    assert len(subs) == 1
    assert subs[0].unified_msg_origin == "platform:group:g1"


@pytest.mark.asyncio
async def test_subscription_delete_is_explicit(tmp_path: Path) -> None:
    """取消订阅返回是否命中，不静默成功。"""

    store = SubscriptionStore(tmp_path / "subscriptions.json")
    await store.add(SIGN_RESULT, origin="origin-1", user_id="user-1")

    assert await store.delete(SIGN_RESULT, "origin-1") is True
    assert await store.delete(SIGN_RESULT, "origin-1") is False
    assert await store.get(SIGN_RESULT) == ()


@pytest.mark.asyncio
async def test_subscription_corrupt_json_fails_visible(tmp_path: Path) -> None:
    """损坏的订阅文件显式失败，不静默清空假装成功。"""

    path = tmp_path / "subscriptions.json"
    path.write_text("{ not json", encoding="utf-8")
    store = SubscriptionStore(path)

    with pytest.raises(RuntimeError):
        await store.get(SIGN_RESULT)


@pytest.mark.asyncio
async def test_add_dedupes_by_uid_within_same_origin(tmp_path: Path) -> None:
    """同会话内不同 uid 的个人订阅互不覆盖。"""

    store = SubscriptionStore(tmp_path / "subscriptions.json")
    await store.add(
        "mh",
        origin="origin-1",
        user_id="user-1",
        uid="user-1",
        extra_message="角色:拆解",
    )
    await store.add(
        "mh",
        origin="origin-1",
        user_id="user-2",
        uid="user-2",
        extra_message="角色:追缉",
    )

    subs = await store.get("mh")
    assert len(subs) == 2
    assert {sub.uid for sub in subs} == {"user-1", "user-2"}

    await store.add(
        "mh",
        origin="origin-1",
        user_id="user-1",
        uid="user-1",
        extra_message="角色:勘探",
    )
    subs = await store.get("mh")
    assert len(subs) == 2
    assert {sub.uid for sub in subs} == {"user-1", "user-2"}


@pytest.mark.asyncio
async def test_delete_is_scoped_by_uid(tmp_path: Path) -> None:
    """删除个人订阅不误删同会话其他用户。"""

    store = SubscriptionStore(tmp_path / "subscriptions.json")
    await store.add("mh", origin="origin-1", user_id="user-1", uid="user-1")
    await store.add("mh", origin="origin-1", user_id="user-2", uid="user-2")

    assert await store.delete("mh", "origin-1", uid="user-1") is True
    subs = await store.get("mh")
    assert [sub.uid for sub in subs] == ["user-2"]
