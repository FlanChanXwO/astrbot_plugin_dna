"""订阅 JSON 存储公开接口回归测试。"""

import asyncio
import json
from pathlib import Path

from src.utils.session import EventContext
from src.utils.subscriptions import SubscriptionStore


def _run(awaitable):
    """在未安装 pytest-asyncio 时运行订阅存储的 async API。"""
    return asyncio.run(awaitable)


def _event(
    *,
    user_id: str,
    bot_id: str,
    unified_msg_origin: str,
    user_type: str = "group",
    group_id: str = "",
    platform: str = "",
) -> EventContext:
    """构造订阅 API 所需的最小事件上下文。"""
    return EventContext(
        user_id=user_id,
        bot_id=bot_id,
        group_id=group_id,
        user_type=user_type,
        unified_msg_origin=unified_msg_origin,
        platform=platform,
    )


def test_subscription_store_init_loads_existing_json(tmp_path: Path):
    """init 会加载既有 JSON，查询结果保留目标与附加数据。"""
    path = tmp_path / "subscriptions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "preloaded",
                    "user_id": "user-1",
                    "bot_id": "bot-1",
                    "unified_msg_origin": "origin-1",
                    "uid": "1001",
                    "extra_message": "已加载",
                    "extra_data": "{\"source\": \"fixture\"}",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = SubscriptionStore(tmp_path / "unused.json")
    _run(store.init(path))

    subscriptions = _run(store.get_subscribe("preloaded", user_id="user-1", uid="1001"))
    assert len(subscriptions) == 1
    assert subscriptions[0].unified_msg_origin == "origin-1"
    assert subscriptions[0].extra_message == "已加载"
    assert subscriptions[0].extra_data == '{"source": "fixture"}'


def test_subscription_lifecycle_deduplicates_by_origin_and_persists(tmp_path: Path):
    """同类型同 UID 的同一 UMO 只保留一条，并支持更新、删除和重载。"""
    path = tmp_path / "subscriptions.json"
    store = SubscriptionStore(path)
    event = _event(
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
        unified_msg_origin="origin-1",
        platform="self-1",
    )

    _run(store.init(path))
    assert _run(store.get_subscribe("daily")) == []

    _run(
        store.add_subscribe(
            "session",
            "daily",
            event,
            uid="1001",
            extra_message="首次消息",
            extra_data="首次数据",
        )
    )
    _run(
        store.add_subscribe(
            "session",
            "daily",
            event,
            uid="1001",
            extra_message="替换消息",
            extra_data="替换数据",
        )
    )

    subscriptions = _run(store.get_subscribe("daily"))
    assert len(subscriptions) == 1
    assert subscriptions[0].unified_msg_origin == "origin-1"
    assert subscriptions[0].bot_self_id == "self-1"
    assert subscriptions[0].extra_message == "替换消息"
    assert subscriptions[0].extra_data == "替换数据"
    assert json.loads(path.read_text(encoding="utf-8"))[0]["extra_message"] == "替换消息"

    _run(store.update_subscribe_message("session", "daily", event, "1001", "更新消息"))
    _run(store.update_subscribe_data("session", "daily", event, "更新数据", "1001"))
    updated = _run(store.get_subscribe("daily", uid="1001"))
    assert len(updated) == 1
    assert updated[0].extra_message == "更新消息"
    assert updated[0].extra_data == "更新数据"

    reloaded = SubscriptionStore(tmp_path / "different-path.json")
    _run(reloaded.init(path))
    persisted = _run(reloaded.get_subscribe("daily", uid="1001"))
    assert len(persisted) == 1
    assert persisted[0].extra_message == "更新消息"
    assert persisted[0].extra_data == "更新数据"

    _run(reloaded.delete_subscribe("session", "daily", event, "1001"))
    assert _run(reloaded.get_subscribe("daily")) == []
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_subscription_query_filters_by_target_fields(tmp_path: Path):
    """订阅查询按类型、用户、Bot、会话类型和 UID 过滤。"""
    path = tmp_path / "subscriptions.json"
    store = SubscriptionStore(path)
    _run(store.init(path))

    event_group_user_1 = _event(
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
        unified_msg_origin="origin-1",
    )
    event_direct_user_1 = _event(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="origin-2",
        user_type="direct",
    )
    event_group_user_2 = _event(
        user_id="user-2",
        bot_id="bot-2",
        group_id="group-2",
        unified_msg_origin="origin-3",
    )
    event_other_type = _event(
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-3",
        unified_msg_origin="origin-4",
    )

    _run(store.add_subscribe("session", "daily", event_group_user_1, uid="uid-1"))
    _run(store.add_subscribe("session", "daily", event_direct_user_1, uid="uid-2"))
    _run(store.add_subscribe("session", "daily", event_group_user_2, uid="uid-3"))
    _run(store.add_subscribe("session", "weekly", event_other_type, uid="uid-1"))

    assert len(_run(store.get_subscribe("daily"))) == 3
    assert len(_run(store.get_subscribe("daily", user_id="user-1"))) == 2
    assert len(_run(store.get_subscribe("daily", bot_id="bot-2"))) == 1
    assert len(_run(store.get_subscribe("daily", user_type="group"))) == 2
    assert len(_run(store.get_subscribe("daily", uid="uid-1"))) == 1
    filtered = _run(
        store.get_subscribe(
            "daily",
            user_id="user-1",
            bot_id="bot-1",
            user_type="group",
            uid="uid-1",
        )
    )
    assert [subscription.unified_msg_origin for subscription in filtered] == ["origin-1"]


def test_subscription_mutations_serialize_read_modify_write(tmp_path: Path):
    """并发变更必须等持久化锁后再读、改、写，避免等待期间提前改内存。"""

    async def snapshot(store: SubscriptionStore) -> list[tuple[str, str, str]]:
        return [
            (subscription.uid, subscription.extra_message, subscription.extra_data)
            for subscription in await store.get_subscribe("daily")
        ]

    async def run_while_lock_is_held(store: SubscriptionStore, operation, before, after):
        # 持锁模拟另一条持久化事务，await 让待测调用进入并发调度点。
        await store._lock.acquire()
        task = asyncio.create_task(operation())
        await asyncio.sleep(0)
        try:
            assert not task.done()
            assert await snapshot(store) == before
        finally:
            store._lock.release()
        await task
        assert await snapshot(store) == after

    async def scenario():
        add_store = SubscriptionStore(tmp_path / "add.json")
        add_event = _event(user_id="add-user", bot_id="bot", unified_msg_origin="add-origin")
        await add_store.init(add_store.path)
        await run_while_lock_is_held(
            add_store,
            lambda: add_store.add_subscribe("session", "daily", add_event, uid="add-uid"),
            [],
            [("add-uid", "", "")],
        )

        delete_store = SubscriptionStore(tmp_path / "delete.json")
        delete_event = _event(
            user_id="delete-user", bot_id="bot", unified_msg_origin="delete-origin"
        )
        await delete_store.init(delete_store.path)
        await delete_store.add_subscribe(
            "session",
            "daily",
            delete_event,
            uid="delete-uid",
            extra_message="before",
            extra_data="before-data",
        )
        await run_while_lock_is_held(
            delete_store,
            lambda: delete_store.delete_subscribe(
                "session", "daily", delete_event, uid="delete-uid"
            ),
            [("delete-uid", "before", "before-data")],
            [],
        )

        message_store = SubscriptionStore(tmp_path / "message.json")
        message_event = _event(
            user_id="message-user", bot_id="bot", unified_msg_origin="message-origin"
        )
        await message_store.init(message_store.path)
        await message_store.add_subscribe(
            "session",
            "daily",
            message_event,
            uid="message-uid",
            extra_message="before",
            extra_data="before-data",
        )
        await run_while_lock_is_held(
            message_store,
            lambda: message_store.update_subscribe_message(
                "session", "daily", message_event, "message-uid", "after"
            ),
            [("message-uid", "before", "before-data")],
            [("message-uid", "after", "before-data")],
        )

        data_store = SubscriptionStore(tmp_path / "data.json")
        data_event = _event(
            user_id="data-user", bot_id="bot", unified_msg_origin="data-origin"
        )
        await data_store.init(data_store.path)
        await data_store.add_subscribe(
            "session",
            "daily",
            data_event,
            uid="data-uid",
            extra_message="before",
            extra_data="before-data",
        )
        await run_while_lock_is_held(
            data_store,
            lambda: data_store.update_subscribe_data(
                "session", "daily", data_event, "after-data", "data-uid"
            ),
            [("data-uid", "before", "before-data")],
            [("data-uid", "before", "after-data")],
        )

    _run(scenario())
