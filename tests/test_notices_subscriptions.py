"""Task 22 密函/公告订阅、推送与取消的隔离契约测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

SHANGHAI = ZoneInfo("Asia/Shanghai")


async def _database_with_binding(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
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
    secret_simple_image: bool = True,
) -> NoticesService:
    return NoticesService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        NoticesRenderer(
            database.path.parent / "rendered",
            EncyclopediaResourceStore.from_root(database.path.parent / "resources"),
            simple_image=secret_simple_image,
        ),
        subscriptions=subscriptions
        or SubscriptionStore(tmp_path / "subscriptions.json"),
        ann_state=AnnStateStore(tmp_path / "ann_state.json"),
        push=push,
        secret_simple_image=secret_simple_image,
        clock=lambda: datetime(2026, 8, 30, 12, 35, tzinfo=SHANGHAI),
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
    third = await service.subscribe_mh(
        _request("订阅追缉密函", {"mh_name": "追缉"}),
    )

    assert isinstance(first, PlainTextResponse)
    assert first.need_at is True
    assert first.text == "成功订阅密函【角色:拆解,武器:拆解,魔之楔:拆解】"
    assert isinstance(second, PlainTextResponse)
    assert second.need_at is True
    assert second.text == "请勿重复订阅密函【拆解】"
    assert isinstance(third, PlainTextResponse)
    assert third.need_at is True
    assert third.text == f"成功订阅密函【追缉】!当前订阅密函: {",".join(sorted({"角色:拆解", "角色:追缉", "武器:拆解", "武器:追缉", "魔之楔:拆解", "魔之楔:追缉"}))}"
    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(
        messages.MH_SUBSCRIBE,
        user_id="user-1",
        bot_id="bot-1",
    )
    assert len(subs) == 1
    assert set(subs[0].extra_message.split(",")) == {"角色:拆解", "角色:追缉", "武器:拆解", "武器:追缉", "魔之楔:拆解", "魔之楔:追缉"}
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_mh_rejects_all(tmp_path: Path) -> None:
    """禁止订阅全部密函。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    response = await service.subscribe_mh(_request("订阅全部密函", {"mh_name": "全部"}))

    assert isinstance(response, PlainTextResponse)
    assert response.need_at is True
    assert response.text == "禁止订阅全部密函, 请使用[kk密函列表]命令查看可订阅密函"
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
    assert response.need_at is True
    assert response.text == f"成功取消订阅密函【拆解】!当前订阅密函: {",".join(sorted({"角色:追缉", "武器:追缉", "魔之楔:追缉"}))}"
    subscriptions = service.subscriptions
    assert subscriptions is not None
    subs = await subscriptions.get(messages.MH_SUBSCRIBE)
    assert set(subs[0].extra_message.split(",")) == {"角色:追缉", "武器:追缉", "魔之楔:追缉"}

    # 取消订阅最后一项时，返回当前订阅密函为空并清理订阅
    last_unsub = await service.unsubscribe_mh(
        _request("取消订阅追缉密函", {"mh_name": "追缉"}),
    )
    assert isinstance(last_unsub, PlainTextResponse)
    assert last_unsub.need_at is True
    assert last_unsub.text == "成功取消订阅密函【追缉】!当前订阅密函: "
    assert await subscriptions.get(messages.MH_SUBSCRIBE) == ()
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
    assert response.need_at is True
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

    # 未订阅时提示未曾订阅密函
    empty_res = await service.mh_subscriptions(_request("我的密函"))
    assert isinstance(empty_res, PlainTextResponse)
    assert empty_res.need_at is True
    assert empty_res.text == "未曾订阅密函"

    # 订阅后无时间限制
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}))
    unlimited_res = await service.mh_subscriptions(_request("我的密函"))
    assert isinstance(unlimited_res, PlainTextResponse)
    assert unlimited_res.need_at is True
    assert unlimited_res.text == (
        "当前订阅密函: 角色:拆解,武器:拆解,魔之楔:拆解\n"
        "推送时间: 不限制\n"
        "可以使用命令设置推送时间: kk订阅密函时间17:23"
    )

    # 设置时间后展示时间段
    time_set_res = await service.set_mh_push_time(
        _request("订阅密函时间17:23", {"start": "17", "end": "23"}),
    )
    assert isinstance(time_set_res, PlainTextResponse)
    assert time_set_res.need_at is True
    assert time_set_res.text == (
        "当前订阅密函: 角色:拆解,武器:拆解,魔之楔:拆解\n"
        "推送时间: 17点-23点"
    )

    response = await service.mh_subscriptions(_request("我的密函"))

    assert isinstance(response, PlainTextResponse)
    assert response.need_at is True
    assert response.text == (
        "当前订阅密函: 角色:拆解,武器:拆解,魔之楔:拆解\n"
        "推送时间: 17点-23点"
    )
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
    assert response.need_at is True
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
    pic_cancel_empty = await service.toggle_mh_pic(_request("取消订阅密函图片", actor=actor))

    text = await service.toggle_mh_text(_request("订阅密函文本", actor=actor))
    text_cancel = await service.toggle_mh_text(_request("取消订阅密函文本", actor=actor))
    text_cancel_empty = await service.toggle_mh_text(_request("取消订阅密函文本", actor=actor))

    assert isinstance(pic, PlainTextResponse) and pic.need_at is True
    assert pic.text == messages.MH_PIC_SUBSCRIBED
    assert isinstance(pic_cancel, PlainTextResponse) and pic_cancel.need_at is True
    assert pic_cancel.text == messages.MH_PIC_UNSUBSCRIBED
    assert isinstance(pic_cancel_empty, PlainTextResponse) and pic_cancel_empty.need_at is True
    assert pic_cancel_empty.text == messages.MH_PIC_NOT_SUBSCRIBED

    assert isinstance(text, PlainTextResponse) and text.need_at is True
    assert text.text == messages.MH_TEXT_SUBSCRIBED
    assert isinstance(text_cancel, PlainTextResponse) and text_cancel.need_at is True
    assert text_cancel.text == messages.MH_TEXT_UNSUBSCRIBED
    assert isinstance(text_cancel_empty, PlainTextResponse) and text_cancel_empty.need_at is True
    assert text_cancel_empty.text == messages.MH_TEXT_NOT_SUBSCRIBED

    subscriptions = service.subscriptions
    assert subscriptions is not None
    assert await subscriptions.get(messages.MH_PIC_SUBSCRIBE) == ()
    assert await subscriptions.get(messages.MH_TEXT_SUBSCRIBE) == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_ann_sub_unsub_group_scoped(tmp_path: Path) -> None:
    """公告订阅仅群聊作用域，重复订阅去重。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeNoticesTransport(), tmp_path)

    first = await service.subscribe_ann(_request("订阅公告"))
    duplicate = await service.subscribe_ann(_request("订阅公告"))
    unsub = await service.unsubscribe_ann(_request("取消订阅公告"))
    unsub_empty = await service.unsubscribe_ann(_request("取消订阅公告"))

    assert isinstance(first, PlainTextResponse) and first.need_at is True
    assert first.text == messages.ANN_SUBSCRIBED
    assert isinstance(duplicate, PlainTextResponse) and duplicate.need_at is True
    assert duplicate.text == messages.ANN_ALREADY_SUBSCRIBED
    assert isinstance(unsub, PlainTextResponse) and unsub.need_at is True
    assert unsub.text == messages.ANN_UNSUBSCRIBED
    assert isinstance(unsub_empty, PlainTextResponse) and unsub_empty.need_at is True
    assert unsub_empty.text == messages.ANN_NOT_SUBSCRIBED

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
    unsub_resp = await service.unsubscribe_ann(
        _request("取消订阅公告", actor=_actor(group=None)),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.need_at is True
    assert response.text == messages.ANN_GROUP_ONLY

    assert isinstance(unsub_resp, PlainTextResponse)
    assert unsub_resp.need_at is True
    assert unsub_resp.text == messages.ANN_GROUP_UNSUB_ONLY
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
    """公告轮询只推送新公告，已推送的 id 不再重复推送，新公告推送渲染图片。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object]] = []
    ann_state = AnnStateStore(tmp_path / "ann_state.json")
    # 预置已推送过的旧公告 id
    await ann_state.merge([1000, 1002])

    async def push(origin: str, payload: object) -> None:
        pushed.append((origin, payload))

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

    assert first == 1  # 1001 是新公告 → 推送给 1 个订阅者
    assert second == 0  # 已推送过，不再重复
    assert len(pushed) == 1
    origin, payload = pushed[0]
    assert origin == "platform:group:g1"
    assert isinstance(payload, Path)
    assert payload.is_file()
    await database.dispose()


@pytest.mark.asyncio
async def test_test_mh_push_sends_to_current_session(tmp_path: Path) -> None:
    """admin 密函测试向当前会话发送。"""

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


@pytest.mark.asyncio
async def test_push_mh_now_filters_by_rotation_and_time_and_text_all(tmp_path: Path) -> None:
    """密函整点推送：按当前轮换与时间段过滤个人订阅，支持全量文本订阅与图片订阅。"""

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

    # 1. 订阅了轮换中存在的密函（拆解在 FakeNoticesTransport 角色轮换中）
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}, actor=_actor(origin="platform:group:g1")))

    # 2. 订阅了轮换中不存在的密函（避险不在 FakeNoticesTransport 中）
    await service.subscribe_mh(_request("订阅避险密函", {"mh_name": "避险"}, actor=_actor(origin="platform:group:g2")))

    # 3. 订阅了全量文本密函
    await service.toggle_mh_text(_request("订阅密函文本", actor=_actor(origin="platform:group:g3")))

    # 4. 订阅了全量图片密函
    await service.toggle_mh_pic(_request("订阅密函图片", actor=_actor(origin="platform:group:g4")))

    count = await service.push_mh_now()

    # g1 (拆解), g3 (全量文本), g4 (图片) 应收到推送，g2 (避险未命中) 不收到
    assert count == 3
    origins = [origin for origin, _ in pushed]
    assert "platform:group:g1" in origins
    assert "platform:group:g2" not in origins
    assert "platform:group:g3" in origins
    assert "platform:group:g4" in origins

    # 验证 g3 全量文本格式
    g3_payload = next(payload for origin, payload in pushed if origin == "platform:group:g3")
    assert "【密函已刷新】" in str(g3_payload)
    assert "-- 角色 --" in str(g3_payload)
    assert "扼守" in str(g3_payload)

    # 验证 g4 图片推送
    g4_payload = next(payload for origin, payload in pushed if origin == "platform:group:g4")
    assert isinstance(g4_payload, Path)
    assert g4_payload.is_file()

    await database.dispose()

@pytest.mark.asyncio
async def test_push_mh_now_continues_when_one_subscriber_push_fails(tmp_path: Path) -> None:
    """密函推送中某订阅者失败时，不影响其他订阅者。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.MH_SUBSCRIBE,
        origin="platform:group:fail_group",
        user_id="user-1",
        bot_id="bot-1",
        group_id="fail_group",
        uid="user-1",
        extra_message="角色:拆解",
    )
    await subscriptions.add(
        messages.MH_SUBSCRIBE,
        origin="platform:group:ok_group",
        user_id="user-2",
        bot_id="bot-1",
        group_id="ok_group",
        uid="user-2",
        extra_message="角色:拆解",
    )
    pushed: list[str] = []

    async def push(origin: str, payload: object) -> None:
        if "fail_group" in origin:
            raise ConnectionResetError("network failed")
        pushed.append(origin)

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )

    count = await service.push_mh_now()

    assert count == 1
    assert pushed == ["platform:group:ok_group"]
    await database.dispose()


@pytest.mark.asyncio
async def test_poll_ann_now_continues_when_one_subscriber_push_fails(tmp_path: Path) -> None:
    """公告推送中某订阅者失败时，不影响其他订阅者。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.ANN_SUBSCRIBE,
        origin="platform:group:fail_group",
        user_id="user-1",
        bot_id="bot-1",
        group_id="fail_group",
        user_type="group",
    )
    await subscriptions.add(
        messages.ANN_SUBSCRIBE,
        origin="platform:group:ok_group",
        user_id="user-2",
        bot_id="bot-1",
        group_id="ok_group",
        user_type="group",
    )
    ann_state = AnnStateStore(tmp_path / "ann_state.json")
    await ann_state.merge([1000, 1002])  # 1001 是新公告
    pushed: list[str] = []

    async def push(origin: str, payload: object) -> None:
        if "fail_group" in origin:
            raise ConnectionResetError("network failed")
        pushed.append(origin)

    service = _service(
        database,
        FakeNoticesTransport(ann_list=_ann_snapshot()),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    object.__setattr__(service, "ann_state", ann_state)

    count = await service.poll_ann_now()

    assert count == 1
    assert pushed == ["platform:group:ok_group"]
    await database.dispose()


@pytest.mark.asyncio
async def test_push_mh_now_includes_at_user_id_for_group_subscriber(tmp_path: Path) -> None:
    """群聊密函订阅在推送时应携带订阅者的 at_user_id。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object, str | None]] = []

    async def push(origin: str, payload: object, at_user_id: str | None = None) -> None:
        pushed.append((origin, payload, at_user_id))

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )
    actor = EventActor(user_id="308597424", bot_id="bot-1", group_id="g100", unified_msg_origin="platform:group:g100")
    req = _request("订阅拆解密函", {"mh_name": "拆解"}, actor=actor)
    await service.subscribe_mh(req)

    count = await service.push_mh_now()

    assert count == 1
    assert len(pushed) == 1
    origin, payload, at_user = pushed[0]
    assert origin == "platform:group:g100"
    assert "角色 : 拆解" in str(payload)
    assert at_user == "308597424"
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe_ann_syncs_to_config_and_saves(tmp_path: Path) -> None:
    """订阅公告和退订公告时，群组 ID 同步到 config[notifications][announcement_groups] 并持久化保存。"""
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    saved = []

    class FakeAstrBotConfig(dict):
        def save_config(self):
            saved.append(True)

    config = FakeAstrBotConfig({
        "notifications": {
            "announcement_groups": {},
        }
    })

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
    )
    service.config_store = config

    actor = EventActor(user_id="10001", bot_id="bot-1", group_id="group-999", unified_msg_origin="platform:group:group-999")
    req = _request("订阅公告", actor=actor)
    sub_res = await service.subscribe_ann(req)
    assert isinstance(sub_res, PlainTextResponse)
    assert "订阅" in sub_res.text
    assert config["notifications"]["announcement_groups"].get("group-999") is True
    assert len(saved) >= 1

    # 退订公告
    unsub_req = _request("退订公告", actor=actor)
    unsub_res = await service.unsubscribe_ann(unsub_req)
    assert isinstance(unsub_res, PlainTextResponse)
    assert "已取消" in unsub_res.text or "退订" in unsub_res.text or "成功" in unsub_res.text
    assert "group-999" not in config["notifications"]["announcement_groups"]
    assert len(saved) >= 2
    await database.dispose()


@pytest.mark.asyncio
async def test_push_mh_pic_and_text_do_not_at_user_while_name_sub_does(tmp_path: Path) -> None:
    """订阅密函图片和订阅密函文本属于全量广播订阅，不产生 at 行为；只有订阅具体名称密函才在群聊中 at 订阅者。"""
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object, str | None]] = []

    async def push(origin: str, payload: object, at_user_id: str | None = None) -> None:
        pushed.append((origin, payload, at_user_id))

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )

    # 1. 群 g1 订阅具体名称密函 拆解
    actor1 = EventActor(user_id="user-1", bot_id="bot-1", group_id="g1", unified_msg_origin="platform:group:g1")
    await service.subscribe_mh(_request("订阅拆解密函", {"mh_name": "拆解"}, actor=actor1))

    # 2. 群 g2 订阅密函文本
    actor2 = EventActor(user_id="user-2", bot_id="bot-1", group_id="g2", unified_msg_origin="platform:group:g2")
    await service.toggle_mh_text(_request("订阅全量密函", actor=actor2))

    # 3. 群 g3 订阅密函图片
    actor3 = EventActor(user_id="user-3", bot_id="bot-1", group_id="g3", unified_msg_origin="platform:group:g3")
    await service.toggle_mh_pic(_request("订阅密函图片", actor=actor3))

    count = await service.push_mh_now()
    assert count == 3

    # 验证推送时的 at_user_id
    push_by_origin = {origin: (payload, at_user) for origin, payload, at_user in pushed}

    # g1 应有 at
    assert "platform:group:g1" in push_by_origin
    assert push_by_origin["platform:group:g1"][1] == "user-1"

    # g2 (文本) 不应有 at
    assert "platform:group:g2" in push_by_origin
    assert push_by_origin["platform:group:g2"][1] is None

    # g3 (图片) 不应有 at
    assert "platform:group:g3" in push_by_origin
    assert push_by_origin["platform:group:g3"][1] is None

    await database.dispose()


@pytest.mark.asyncio
async def test_push_mh_now_aggregates_multiple_group_subscribers_with_ats_at_end(tmp_path: Path) -> None:
    """同一群聊中多个用户订阅并触发密函刷新时，应聚合成一条推送消息，且所有 at 堆在末尾。"""
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    pushed: list[tuple[str, object, Any]] = []

    async def push(origin: str, payload: object, at_user_id: Any = None) -> None:
        pushed.append((origin, payload, at_user_id))

    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
        push=push,
    )

    # 3 个用户在同一个群聊中分别订阅 拆解 密函
    origin = "platform:group:g100"
    for user_id in ("user-1", "user-2", "user-3"):
        actor = EventActor(user_id=user_id, bot_id="bot-1", group_id="g100", unified_msg_origin=origin)
        req = _request("订阅拆解密函", {"mh_name": "拆解"}, actor=actor)
        await service.subscribe_mh(req)

    count = await service.push_mh_now()

    # 聚合成 1 条推送
    assert count == 1
    assert len(pushed) == 1
    push_origin, payload, at_users = pushed[0]
    assert push_origin == origin
    assert "当前订阅密函已刷新:\n角色 : 拆解" in str(payload)
    # at_users 应包含 3 个用户
    assert at_users == ["user-1", "user-2", "user-3"]

    await database.dispose()


@pytest.mark.asyncio
async def test_bootstrap_push_notice_formats_ats_at_the_end() -> None:
    """验证 _push_notice 在构造 MessageChain 时将所有 at 放在正文换行之后的末尾。"""
    from astrbot.api.message_components import At, Plain
    from astrbot.core.message.message_event_result import MessageChain

    from src.bootstrap import build_runtime

    sent_messages: list[tuple[str, MessageChain]] = []

    class FakeContext:
        def send_message(self, origin: str, msg: MessageChain) -> None:
            sent_messages.append((origin, msg))

    runtime = build_runtime(FakeContext(), config={})
    notices_service = runtime.services["notices_service"]
    push_fn = notices_service.push

    # 模拟推送给 3 个用户的群聊消息
    await push_fn(
        "platform:group:g100",
        "当前订阅密函已刷新:\n角色 : 探险",
        at_user_id=["1", "2", "3"],
    )

    assert len(sent_messages) == 1
    origin, msg_chain = sent_messages[0]
    assert origin == "platform:group:g100"

    chain = msg_chain.chain
    # 第一个组件为正文 Plain，结尾带 \n 以免被 AstrBot 平台适配器（如 OneBot）过滤单独的 \n 组件
    assert isinstance(chain[0], Plain)
    assert chain[0].text == "当前订阅密函已刷新:\n角色 : 探险\n"
    # 后续组件为 At 和空格
    assert isinstance(chain[1], At)
    assert str(chain[1].qq) == "1"
    assert isinstance(chain[2], Plain)
    assert chain[2].text == " "
    assert isinstance(chain[3], At)
    assert str(chain[3].qq) == "2"
    assert isinstance(chain[4], Plain)
    assert chain[4].text == " "
    assert isinstance(chain[5], At)
    assert str(chain[5].qq) == "3"
