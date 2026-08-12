"""Task 22 密函/公告订阅、推送与取消的隔离契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import NoticesRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from src.modules.notices.ann_state import AnnStateStore
from src.modules.notices.service import NoticesService
from src.modules.privacy import PrivacyService
from tests.test_notices import FakeNoticesTransport, _ann_snapshot


async def _database_with_binding(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )
    return database


def _service(
    database: AsyncDatabase,
    transport: FakeNoticesTransport,
    tmp_path: Path,
    *,
    push=None,
    subscriptions: SubscriptionStore | None = None,
) -> NoticesService:
    return NoticesService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        NoticesRenderer(
            database.path.parent / "rendered",
            EncyclopediaResourceStore.from_root(database.path.parent / "resources"),
        ),
        subscriptions=subscriptions
        or SubscriptionStore(tmp_path / "subscriptions.json"),
        ann_state=AnnStateStore(tmp_path / "ann_state.json"),
        push=push,
    )


def _actor(*, origin: str = "platform:group:g1", group: str | None = "group-1") -> EventActor:
    return EventActor("user-1", "bot-1", group, unified_msg_origin=origin)


def _request(text: str, parameters: dict | None = None, actor: EventActor | None = None):
    from src.modules.notices.contracts import NoticeRequest

    return NoticeRequest(
        actor=actor or _actor(),
        target_user_id=None,
        text=text,
        parameters=parameters or {},
    )


@pytest.mark.asyncio
async def test_subscribe_mh_adds_names_and_dedupes(tmp_path: Path) -> None:
    """订阅密函追加名称并去重；重复订阅显式提示。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    first = await service.subscribe_mh(
        _request("订阅拆解密函", {"mh_name": "拆解"}),
    )
    second = await service.subscribe_mh(
        _request("订阅拆解密函", {"mh_name": "拆解"}),
    )

    assert isinstance(first, PlainTextResponse)
    assert "角色:拆解" in first.text
    assert messages.MH_DUPLICATE.format(name="拆解") in second.text
    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(
        messages.MH_SUBSCRIBE,
        user_id="user-1",
        bot_id="bot-1",
    )
    assert len(subs) == 1
    assert set(subs[0].extra_message.split(",")) == {"角色:拆解", "武器:拆解", "魔之楔:拆解"}
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_mh_rejects_all(tmp_path: Path) -> None:
    """禁止订阅全部密函。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    response = await service.subscribe_mh(_request("订阅全部密函", {"mh_name": "全部"}))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.MH_ALL_FORBIDDEN
    await database.dispose()


@pytest.mark.asyncio
async def test_unsubscribe_mh_removes_names(tmp_path: Path) -> None:
    """取消订阅移除指定名称并保留其余。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}))
    await service.subscribe_mh(_request("订阅追缉密函", {"mh_name": "追缉"}))

    response = await service.unsubscribe_mh(
        _request("取消订阅拆解密函", {"mh_name": "拆解"}),
    )

    assert isinstance(response, PlainTextResponse)
    assert "拆解" in response.text
    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(messages.MH_SUBSCRIBE)
    assert set(subs[0].extra_message.split(",")) == {"角色:追缉", "武器:追缉", "魔之楔:追缉"}
    await database.dispose()


@pytest.mark.asyncio
async def test_unsubscribe_mh_all_deletes_subscription(tmp_path: Path) -> None:
    """取消订阅全部删除整条订阅。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}))

    response = await service.unsubscribe_mh(
        _request("取消订阅全部密函", {"mh_name": "全部"}),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.MH_UNSUBSCRIBED_ALL
    subscriptions = service.subscriptions
    assert subscriptions is not None
    assert await subscriptions.get(messages.MH_SUBSCRIBE) == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_subscriptions_shows_time_window(tmp_path: Path) -> None:
    """订阅查看展示名称与推送时间。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}))
    await service.set_mh_push_time(
        _request("订阅密函时间17:23", {"start": "17", "end": "23"}),
    )

    response = await service.mh_subscriptions(_request("我的密函"))

    assert isinstance(response, PlainTextResponse)
    assert "角色:拆解" in response.text
    assert messages.MH_PUSH_TIME_SET.format(start="17", end="23") in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_set_mh_push_time_invalid_hours_is_visible(tmp_path: Path) -> None:
    """推送时间越界返回格式提示。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    response = await service.set_mh_push_time(
        _request("订阅密函时间99:23", {"start": "99", "end": "23"}),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.MH_PUSH_TIME_FORMAT
    await database.dispose()


@pytest.mark.asyncio
async def test_toggle_mh_pic_and_text_are_session_scoped(tmp_path: Path) -> None:
    """图片/文本订阅按会话作用域增删。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)
    actor = _actor()

    pic = await service.toggle_mh_pic(_request("订阅密函图片", actor=actor))
    pic_cancel = await service.toggle_mh_pic(_request("取消订阅密函图片", actor=actor))
    text = await service.toggle_mh_text(_request("订阅密函文本", actor=actor))

    assert pic.text == messages.MH_PIC_SUBSCRIBED
    assert pic_cancel.text == messages.MH_PIC_UNSUBSCRIBED
    assert text.text == messages.MH_TEXT_SUBSCRIBED
    subscriptions = service.subscriptions
    assert subscriptions is not None
    assert await subscriptions.get(messages.MH_PIC_SUBSCRIBE) == ()
    assert len(await subscriptions.get(messages.MH_TEXT_SUBSCRIBE)) == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_sub_unsub_group_scoped(tmp_path: Path) -> None:
    """公告订阅仅群聊作用域，重复订阅去重。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    first = await service.subscribe_ann(_request("订阅公告"))
    duplicate = await service.subscribe_ann(_request("订阅公告"))
    unsub = await service.unsubscribe_ann(_request("取消订阅公告"))

    assert first.text == messages.ANN_SUBSCRIBED
    assert duplicate.text == messages.ANN_ALREADY_SUBSCRIBED
    assert unsub.text == messages.ANN_UNSUBSCRIBED
    subscriptions = service.subscriptions
    assert subscriptions is not None
    assert await subscriptions.get(messages.ANN_SUBSCRIBE) == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_sub_requires_group(tmp_path: Path) -> None:
    """非群聊订阅公告返回显式提示。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    response = await service.subscribe_ann(
        _request("订阅公告", actor=_actor(group=None)),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.ANN_GROUP_ONLY
    await database.dispose()


@pytest.mark.asyncio
async def test_push_mh_now_pushes_text_and_pic_to_subscribers(tmp_path: Path) -> None:
    """计划任务推送：文本订阅者收到文本、图片订阅者收到渲染图。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []

    async def push(origin: str, payload: object) -> None:
        pushed.append((origin, payload))

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}))
    await subscriptions.add(
        messages.MH_PIC_SUBSCRIBE,
        origin="platform:group:g2",
        user_id="user-9",
        bot_id="bot-1",
    )

    count = await service.push_mh_now()

    assert count == 2
    text_targets = [target for target, payload in pushed if isinstance(payload, str)]
    image_targets = [target for target, payload in pushed if isinstance(payload, Path)]
    assert "platform:group:g1" in text_targets
    assert any("角色 : 拆解" in str(payload) for _, payload in pushed)
    assert "platform:group:g2" in image_targets
    assert all(Path(payload).is_file() for _, payload in pushed if isinstance(payload, Path))
    await database.dispose()


@pytest.mark.asyncio
async def test_poll_ann_now_pushes_only_new_announcements(tmp_path: Path) -> None:
    """公告轮询只推送新公告，已推送的 id 不再重复推送。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, str]] = []
    ann_state = AnnStateStore(tmp_path / "ann_state.json")
    # 预置一个已推送过的旧公告 id，模拟第一次轮询初始化后的状态。
    await ann_state.merge([1000])

    async def push(origin: str, payload: object) -> None:
        pushed.append((origin, str(payload)))

    service = _service(
        database,
        FakeNoticesTransport(ann_list=_ann_snapshot()),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    object.__setattr__(service, "ann_state", ann_state)
    await service.subscribe_ann(_request("订阅公告"))

    first = await service.poll_ann_now()
    second = await service.poll_ann_now()

    assert first == 1  # 1001/1002 是新公告 → 推送给 1 个订阅者
    assert second == 0  # 已推送过，不再重复
    assert "最新公告:" in pushed[0][1]
    assert "版本更新公告" in pushed[0][1]
    await database.dispose()


@pytest.mark.asyncio
async def test_test_mh_push_sends_to_current_session(tmp_path: Path) -> None:
    """owner 密函测试向当前会话发送。"""

    database = await _database_with_binding(tmp_path)
    pushed: list[tuple[str, str]] = []

    async def push(origin: str, payload: object) -> None:
        pushed.append((origin, str(payload)))

    service = _service(database, FakeNoticesTransport(), tmp_path, push=push)

    response = await service.test_mh_push(_request("密函测试"))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.MH_TEST_SENT
    assert pushed == [("platform:group:g1", "密函测试推送")]
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_subscription_is_scoped_per_conversation(tmp_path: Path) -> None:
    """同一用户在不同会话的密函订阅互不串扰。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}, actor=_actor(origin="platform:group:a")))
    await service.subscribe_mh(_request("订阅追缉密函", {"mh_name": "追缉"}, actor=_actor(origin="platform:group:b")))

    view_b = await service.mh_subscriptions(_request("我的密函", actor=_actor(origin="platform:group:b")))
    unsub_a = await service.unsubscribe_mh(
        _request("取消订阅拆解密函", {"mh_name": "拆解"}, actor=_actor(origin="platform:group:a")),
    )

    assert "追缉" in view_b.text
    assert "拆解" not in view_b.text
    assert "成功取消订阅密函【拆解】" in unsub_a.text
    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(
        messages.MH_SUBSCRIBE,
        user_id="user-1",
        bot_id="bot-1",
    )
    assert len(subs) == 1  # a 会话已删除，b 会话保留
    assert subs[0].unified_msg_origin == "platform:group:b"
    await database.dispose()


@pytest.mark.asyncio
async def test_mh_subscription_keeps_two_users_in_same_conversation(tmp_path: Path) -> None:
    """同一会话内两个用户订阅互不覆盖。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    async def subscribe(user_id: str, name: str) -> None:
        from src.modules.notices.contracts import NoticeRequest

        await service.subscribe_mh(
            NoticeRequest(
                actor=EventActor(user_id, "bot-1", "group-1", unified_msg_origin="platform:group:g1"),
                target_user_id=None,
                text=f"订阅{name}密函",
                parameters={"mh_name": name},
            ),
        )

    await subscribe("user-1", "拆解")
    await subscribe("user-2", "追缉")

    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(messages.MH_SUBSCRIBE)
    assert len(subs) == 2
    assert {sub.uid for sub in subs} == {"user-1", "user-2"}
    await database.dispose()
