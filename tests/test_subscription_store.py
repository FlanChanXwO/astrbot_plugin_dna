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
