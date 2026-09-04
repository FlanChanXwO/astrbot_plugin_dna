"""Task 17 签到 use case 的 fixture、隔离 DB 和渲染契约。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    PrivacySettingRepository,
    SignRecordRepository,
)
from src.infrastructure.rendering import CheckinRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.checkin import messages
from src.modules.checkin.contracts import (
    CheckinCommandRequest,
    CheckinFailureKind,
    CheckinTransportError,
    CommunityPost,
    CommunityTask,
    DayAward,
    SignCalendar,
    SignPeriod,
    SignRoleInfo,
    SignStatus,
    TaskProcess,
)
from src.modules.checkin.service import CheckinService
from src.modules.privacy import PrivacyService

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
UID = "1234567890123"
TARGET_UID = "9876543210987"


def _calendar_fixture(*, today_signed: bool | None = False) -> SignCalendar:
    return SignCalendar(
        today_signed=today_signed,
        user_gold=123,
        signin_time=3,
        day_awards=tuple(
            DayAward(
                award_id=index,
                period_id=9,
                day_in_period=day,
                award_name=f"奖励{day}",
                award_num=5,
                icon_url=f"icon://award-{day}",
            )
            for index, day in enumerate(range(1, 8))
        ),
        period=SignPeriod(
            period_id=9, name="周期甲", over_days=7, start_date=0, end_date=0
        ),
        role_info=SignRoleInfo(role_id="101", role_name="角色甲", level=60),
    )


def _task_fixture() -> TaskProcess:
    return TaskProcess(
        daily_tasks=(
            CommunityTask(
                mark_name="bbs_sign",
                remark="签到",
                complete_times=0,
                times=1,
                process=0.0,
            ),
        ),
    )


def _posts_fixture(count: int = 4) -> tuple[CommunityPost, ...]:
    return tuple(
        CommunityPost(post_id=f"post-{index}", payload={"postId": f"post-{index}"})
        for index in range(count)
    )


class FakeCheckinTransport:
    """不触碰网络的签到 transport fixture。"""

    def __init__(
        self,
        *,
        calendar: SignCalendar | None = None,
        game_result: SignStatus = SignStatus.DONE,
        task_process: TaskProcess | None = None,
        bbs_result: SignStatus = SignStatus.DONE,
        total_days: int = 12,
        posts: tuple[CommunityPost, ...] = (),
        post_ok: bool = True,
        fail: CheckinTransportError | None = None,
        fail_uid: str | None = None,
    ) -> None:
        self.calendar = calendar if calendar is not None else _calendar_fixture()
        self.game_result = game_result
        self.task_process = (
            task_process if task_process is not None else _task_fixture()
        )
        self.bbs_result = bbs_result
        self.total_days = total_days
        self.posts = posts
        self.post_ok = post_ok
        self.fail = fail
        self.fail_uid = fail_uid
        self.calls: list[str] = []

    def _maybe_fail(self, uid: str, name: str) -> None:
        self.calls.append(name)
        if self.fail is not None and (self.fail_uid is None or self.fail_uid == uid):
            raise self.fail

    async def get_sign_calendar(
        self, actor, uid, *, credential_user_id
    ) -> SignCalendar:
        self._maybe_fail(uid, "get_sign_calendar")
        assert credential_user_id == "user-1"
        return self.calendar

    async def game_sign(
        self, actor, uid, award: DayAward, *, credential_user_id
    ) -> SignStatus:
        self._maybe_fail(uid, "game_sign")
        assert award.award_id == 3
        assert award.day_in_period == 4
        return self.game_result

    async def get_task_process(self, actor, uid, *, credential_user_id) -> TaskProcess:
        self._maybe_fail(uid, "get_task_process")
        return self.task_process

    async def bbs_sign(self, actor, uid, *, credential_user_id) -> SignStatus:
        self._maybe_fail(uid, "bbs_sign")
        return self.bbs_result

    async def have_sign_in(self, actor, uid, *, credential_user_id) -> int:
        self._maybe_fail(uid, "have_sign_in")
        return self.total_days

    async def get_role_overview(self, actor, uid, *, credential_user_id):
        self._maybe_fail(uid, "get_role_overview")
        from src.modules.player.contracts import RoleOverview

        return RoleOverview(
            role_id="role-1",
            role_name="测试玩家",
            level=42,
            achievement_total=3,
            params=[],
            role_chars=[],
            ranged_weapons=[],
            close_weapons=[],
        )

    async def get_post_list(
        self, actor, uid, *, credential_user_id
    ) -> tuple[CommunityPost, ...]:
        self._maybe_fail(uid, "get_post_list")
        return self.posts

    async def get_post_detail(self, actor, uid, post, *, credential_user_id) -> bool:
        self._maybe_fail(uid, "get_post_detail")
        return self.post_ok

    async def do_like(self, actor, uid, post, *, credential_user_id) -> bool:
        self._maybe_fail(uid, "do_like")
        return self.post_ok

    async def do_share(self, actor, uid, *, credential_user_id) -> bool:
        self._maybe_fail(uid, "do_share")
        return self.post_ok

    async def do_reply(self, actor, uid, post, *, credential_user_id) -> bool:
        self._maybe_fail(uid, "do_reply")
        return self.post_ok


async def _database_with_binding(
    tmp_path: Path,
    *,
    user_id: str = "user-1",
    uid: str = UID,
) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "checkin.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            group_id="group-1",
            is_active=True,
        )
    return database


def _service(
    database: AsyncDatabase,
    transport: FakeCheckinTransport,
    *,
    community_tasks: tuple[str, ...] = ("bbs_sign",),
    concurrency: int = 1,
    interval_range: tuple[int, int] = (0, 0),
    allow_mention_query: bool = True,
    subscriptions: SubscriptionStore | None = None,
) -> CheckinService:
    return CheckinService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=allow_mention_query),
        CheckinRenderer(
            database.path.parent / "rendered",
            EncyclopediaResourceStore.from_root(database.path.parent / "resources"),
        ),
        community_tasks=community_tasks,
        concurrency=concurrency,
        interval_range=interval_range,
        subscriptions=subscriptions,
    )


def _request(
    *,
    actor: EventActor | None = None,
    target_user_id: str | None = None,
    text: str = "签到",
) -> CheckinCommandRequest:
    return CheckinCommandRequest(
        actor=actor if actor is not None else EventActor("user-1", "bot-1", "group-1"),
        target_user_id=target_user_id,
        text=text,
    )


@pytest.mark.asyncio
async def test_manual_sign_completes_game_and_community_and_saves_record(
    tmp_path: Path,
) -> None:
    """签到成功必须保存当天记录并返回完成文案。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.sign_status(SignStatus.DONE) in response.text
    assert "社区任务:" in response.text
    assert "签到: ✅ 已完成" in response.text
    async with database.session() as session:
        record = await SignRecordRepository.get(
            session,
            uid=UID,
            record_date=datetime.now(tz=SHANGHAI_TZ).date(),
        )
    assert record is not None
    assert record.game_sign == 1
    assert record.bbs_sign == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_skips_without_transport_when_already_complete(
    tmp_path: Path,
) -> None:
    """今天已完成的账号直接提示重复签到，不调用 transport。"""

    database = await _database_with_binding(tmp_path)
    async with database.transaction() as session:
        await SignRecordRepository.save(
            session,
            uid=UID,
            record_date=datetime.now(tz=SHANGHAI_TZ).date(),
            game_sign=1,
            bbs_sign=1,
            bbs_detail=0,
            bbs_like=0,
            bbs_share=0,
            bbs_reply=0,
        )
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.CHECKIN_ALREADY in response.text
    assert transport.calls == []
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_transport_failure_is_visible_and_redacted(
    tmp_path: Path,
) -> None:
    """transport 错误只映射稳定文案，不回显上游正文。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        fail=CheckinTransportError(
            CheckinFailureKind.NETWORK,
            resource="签到日历",
            detail="token=secret-upstream-001",
        ),
    )
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.transport_error(CheckinFailureKind.NETWORK) in response.text
    assert "secret-upstream-001" not in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_incomplete_calendar_is_visible_failure(
    tmp_path: Path,
) -> None:
    """后端精简返回日历时不伪造成功，游戏签到标为失败。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(calendar=_calendar_fixture(today_signed=None))
    incomplete = SignCalendar(
        today_signed=None,
        user_gold=None,
        signin_time=None,
        day_awards=(),
        period=SignPeriod(
            period_id=9, name="周期甲", over_days=7, start_date=0, end_date=0
        ),
        role_info=None,
    )
    transport = FakeCheckinTransport(calendar=incomplete)
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.sign_status(SignStatus.FAILED) in response.text
    assert "game_sign" not in transport.calls
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_bbs_detail_completes_via_post_iteration(
    tmp_path: Path,
) -> None:
    """浏览任务按目标次数遍历帖子后完成并保存计数。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        task_process=TaskProcess(
            daily_tasks=(
                CommunityTask(
                    mark_name="bbs_detail",
                    remark="浏览",
                    complete_times=0,
                    times=3,
                    process=0.0,
                ),
            ),
        ),
        posts=_posts_fixture(4),
    )
    service = _service(database, transport, community_tasks=("bbs_detail",))

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert "浏览: ✅ 已完成" in response.text
    async with database.session() as session:
        record = await SignRecordRepository.get(
            session,
            uid=UID,
            record_date=datetime.now(tz=SHANGHAI_TZ).date(),
        )
    assert record is not None
    assert record.bbs_detail == 3
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_bbs_post_failures_are_visible(tmp_path: Path) -> None:
    """连续浏览失败必须显露错误，不静默吞掉。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        task_process=TaskProcess(
            daily_tasks=(
                CommunityTask(
                    mark_name="bbs_like",
                    remark="点赞",
                    complete_times=0,
                    times=5,
                    process=0.0,
                ),
            ),
        ),
        posts=_posts_fixture(4),
        post_ok=False,
    )
    service = _service(database, transport, community_tasks=("bbs_like",))

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.CHECKIN_LIKE_FAILED in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_sign_calendar_renders_runtime_image(tmp_path: Path) -> None:
    """签到日历复用 legacy 1300 宽绘制核心。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    from src.utils.resource.RESOURCE_PATH import SIGN_PATH

    for award in transport.calendar.day_awards:
        icon_path = SIGN_PATH / award.icon_url.split("/")[-1]
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (140, 140), (80, 120, 160, 255)).save(icon_path, format="PNG")

    response = await service.sign_calendar(_request())

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    image_path = Path(response.image)
    with Image.open(image_path) as image:
        assert image.width == 1300
        assert image.height == 990
        assert image.convert("RGB").getbbox() == (0, 0, image.width, image.height)
    await database.dispose()


@pytest.mark.asyncio
async def test_sign_all_aggregates_success_and_failure(tmp_path: Path) -> None:
    """全部签到按绑定聚合成功/失败计数。"""

    database = await _database_with_binding(tmp_path)
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            uid="2222222222222",
            group_id="group-1",
            is_active=True,
        )
    transport = FakeCheckinTransport(fail_uid="2222222222222")
    service = _service(database, transport)

    response = await service.sign_all(_request(text="全部签到"))

    assert isinstance(response, PlainTextResponse)
    assert messages.CHECKIN_ALL_DONE in response.text
    assert "成功签到 1 个账号，失败 1 个账号" in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_uid_invalid_when_unbound(tmp_path: Path) -> None:
    """无绑定返回显式 UID 提示。"""

    database = AsyncDatabase(tmp_path / "checkin.sqlite3")
    await database.create_schema_for_tests()
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert response.text == "当前未绑定账号，请先登录"
    assert transport.calls == []
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_peek_blocked_visible(tmp_path: Path) -> None:
    """目标用户防偷窥时显式拒绝，不执行签到。"""

    database = await _database_with_binding(
        tmp_path, user_id="target-1", uid=TARGET_UID
    )
    async with database.transaction() as session:
        await PrivacySettingRepository.add(
            session,
            user_id="target-1",
            group_id=None,
            allow_peek=False,
        )
    transport = FakeCheckinTransport()
    service = _service(database, transport, allow_mention_query=True)

    response = await service.manual_sign(
        _request(
            actor=EventActor("user-1", "bot-1", "group-1"), target_user_id="target-1"
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.CHECKIN_PEEK_BLOCKED
    assert transport.calls == []
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_sign_result_adds_and_dedupes(tmp_path: Path) -> None:
    """订阅签到结果写入订阅存储并按会话去重。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    transport = FakeCheckinTransport()
    service = _service(database, transport, subscriptions=subscriptions)
    actor = EventActor(
        "user-1", "bot-1", "group-1", unified_msg_origin="platform:group:g1"
    )

    response = await service.subscribe_sign_result(
        _request(actor=actor, text="订阅签到结果"),
    )
    again = await service.subscribe_sign_result(
        _request(actor=actor, text="订阅签到结果"),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.SIGN_RESULT_SUBSCRIBED
    assert isinstance(again, PlainTextResponse)
    assert again.text == messages.SIGN_RESULT_SUBSCRIBED
    subs = await subscriptions.get(messages.SIGN_RESULT_SUBSCRIBE)
    assert len(subs) == 1
    assert subs[0].unified_msg_origin == "platform:group:g1"
    await database.dispose()


@pytest.mark.asyncio
async def test_unsubscribe_sign_result_removes_subscription(tmp_path: Path) -> None:
    """取消订阅删除对应会话的订阅。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    transport = FakeCheckinTransport()
    service = _service(database, transport, subscriptions=subscriptions)
    actor = EventActor(
        "user-1", "bot-1", "group-1", unified_msg_origin="platform:group:g1"
    )
    await service.subscribe_sign_result(_request(actor=actor, text="订阅签到结果"))

    response = await service.subscribe_sign_result(
        _request(actor=actor, text="取消订阅签到结果"),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.SIGN_RESULT_UNSUBSCRIBED
    assert await subscriptions.get(messages.SIGN_RESULT_SUBSCRIBE) == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_sign_result_without_origin_is_visible(tmp_path: Path) -> None:
    """无法定位会话时不写入订阅并显式提示。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    transport = FakeCheckinTransport()
    service = _service(database, transport, subscriptions=subscriptions)

    response = await service.subscribe_sign_result(
        _request(actor=EventActor("user-1", "bot-1", "group-1"), text="订阅签到结果"),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.SIGN_RESULT_ORIGIN_MISSING
    assert await subscriptions.get(messages.SIGN_RESULT_SUBSCRIBE) == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_all_summary_counts_game_and_community(tmp_path: Path) -> None:
    """自动签到摘要区分游戏/社区成功数。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    text = await service.auto_sign_all()

    assert "[二重螺旋]自动任务" in text
    assert "今日成功游戏签到 1 个账号" in text
    assert "今日社区签到 1 个账号" in text
    await database.dispose()


@pytest.mark.asyncio
async def test_clear_sign_records_before_deletes_old_records(tmp_path: Path) -> None:
    """清理早于指定日期的签到记录并返回条数。"""

    database = await _database_with_binding(tmp_path)
    async with database.transaction() as session:
        await SignRecordRepository.save(
            session,
            uid=UID,
            record_date=date(2026, 8, 9),
            game_sign=1,
            bbs_sign=1,
            bbs_detail=0,
            bbs_like=0,
            bbs_share=0,
            bbs_reply=0,
        )
        await SignRecordRepository.save(
            session,
            uid=UID,
            record_date=date(2026, 8, 11),
            game_sign=1,
            bbs_sign=1,
            bbs_detail=0,
            bbs_like=0,
            bbs_share=0,
            bbs_reply=0,
        )
    transport = FakeCheckinTransport()
    service = _service(database, transport)

    deleted = await service.clear_sign_records_before(date(2026, 8, 11))

    assert deleted == 1
    async with database.session() as session:
        remaining = await SignRecordRepository.get(
            session,
            uid=UID,
            record_date=date(2026, 8, 11),
        )
    assert remaining is not None
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_sign_reports_tasks_empty_when_no_enabled_task(
    tmp_path: Path,
) -> None:
    """社区启用但 API 未返回启用任务时，显示明确文案而非帖子列表为空。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        task_process=TaskProcess(
            daily_tasks=(
                CommunityTask(
                    mark_name="bbs_like",
                    remark="点赞",
                    complete_times=0,
                    times=5,
                    process=0.0,
                ),
            ),
        ),
    )
    service = _service(database, transport, community_tasks=("bbs_detail",))

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert messages.CHECKIN_TASKS_EMPTY in response.text
    assert "bbs_like" not in transport.calls
    await database.dispose()


@pytest.mark.asyncio
async def test_subscribe_sign_result_surfaces_corrupt_store(tmp_path: Path) -> None:
    """订阅文件损坏时返回可见错误，不让 handler 崩溃。"""

    database = await _database_with_binding(tmp_path)
    path = tmp_path / "subscriptions.json"
    path.write_text("{ not json", encoding="utf-8")
    subscriptions = SubscriptionStore(path)
    transport = FakeCheckinTransport()
    service = _service(database, transport, subscriptions=subscriptions)
    actor = EventActor(
        "user-1", "bot-1", "group-1", unified_msg_origin="platform:group:g1"
    )

    response = await service.subscribe_sign_result(
        _request(actor=actor, text="订阅签到结果"),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.SIGN_RESULT_STORE_UNAVAILABLE
    await database.dispose()
