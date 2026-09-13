"""Task 17 签到 use case 的 fixture、隔离 DB 和渲染契约。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse
from src.infrastructure.http.app import AppTransportError, AppTransportFailureKind
from src.infrastructure.http.auth import is_credential_failure
from src.infrastructure.http.checkin import DnaApiCheckinTransport, _app_error
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
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
    CheckinOutcome,
    CheckinSummary,
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
from src.modules.checkin.service import CheckinService, _CheckinBatchResult
from src.modules.privacy import PrivacyService

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
UID = "1234567890123"
TARGET_UID = "9876543210987"


def test_checkin_app_http_auth_failure_is_credential_error() -> None:
    """HTTP authentication failures must not degrade into generic service errors."""

    error = _app_error(
        AppTransportError(
            AppTransportFailureKind.STATUS,
            method="POST",
            url="https://dnabbs-api.yingxiong.com/example",
            status_code=401,
        ),
        resource="签到日历",
    )

    assert error.kind is CheckinFailureKind.CREDENTIAL


def test_sign_calendar_projection_accepts_upstream_compact_payload() -> None:
    """The compact upstream calendar response may omit status and awards."""

    calendar = DnaApiCheckinTransport._sign_calendar(
        {
            "period": {
                "id": 1,
                "name": "周期",
                "overDays": 30,
                "startDate": 0,
                "endDate": 0,
            }
        }
    )

    assert calendar.today_signed is None
    assert calendar.signin_time is None
    assert calendar.day_awards == ()


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


def _task_fixture_with_reply() -> TaskProcess:
    """复用基础社区签到任务，并补一个代表性的回复附加任务。"""

    return TaskProcess(
        daily_tasks=(
            *_task_fixture().daily_tasks,
            CommunityTask(
                mark_name="bbs_reply",
                remark="回复",
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
        await CredentialRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            app_cookie="test-token",
            app_device_code="test-device",
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
    group_report: bool = False,
    group_report_image: bool = False,
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
        group_report=group_report,
        group_report_image=group_report_image,
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
async def test_manual_sign_credential_failure_requests_login(tmp_path: Path) -> None:
    """Credential failures must ask the current user to log in again."""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        fail=CheckinTransportError(
            CheckinFailureKind.CREDENTIAL,
            resource="账号凭据",
        ),
    )
    service = _service(database, transport)

    response = await service.manual_sign(_request())

    assert isinstance(response, PlainTextResponse)
    assert response.text == "登录已失效，请重新登录"
    async with database.session() as session:
        record = await CredentialRepository.get(session, user_id="user-1", uid=UID)
    assert record is not None
    assert record.app_status == "无效"
    await database.dispose()


def test_identity_validation_failure_is_credential_failure() -> None:
    """上游身份校验失败必须映射为登录失效，而不是服务异常。"""

    class Response:
        code = 220
        msg = "用户身份校验失败"

    assert is_credential_failure(Response()) is True


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
async def test_subscribe_group_report_is_independent_and_group_only(
    tmp_path: Path,
) -> None:
    """本群报告订阅使用独立类型，且私聊不能创建群订阅。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    service = _service(
        database,
        FakeCheckinTransport(),
        subscriptions=subscriptions,
        group_report=True,
    )
    actor = EventActor(
        "user-1", "bot-1", "group-1", unified_msg_origin="platform:group:g1"
    )

    response = await service.subscribe_group_report(
        _request(actor=actor, text="订阅本群签到报告")
    )
    global_response = await service.subscribe_sign_result(
        _request(actor=actor, text="订阅签到结果")
    )
    private_response = await service.subscribe_group_report(
        _request(
            actor=EventActor(
                "user-1", "bot-1", None, unified_msg_origin="platform:direct:u1"
            ),
            text="订阅本群签到报告",
        )
    )

    assert response.text == messages.SIGN_GROUP_REPORT_SUBSCRIBED
    assert global_response.text == messages.SIGN_RESULT_SUBSCRIBED
    assert private_response.text == messages.SIGN_GROUP_REPORT_GROUP_ONLY
    assert len(await subscriptions.get(messages.SIGN_GROUP_REPORT_SUBSCRIBE)) == 1
    assert len(await subscriptions.get(messages.SIGN_RESULT_SUBSCRIBE)) == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_group_report_unsubscribe_works_when_config_is_disabled(
    tmp_path: Path,
) -> None:
    """关闭群报告后禁止新增，但取消订阅仍能清理旧记录。"""

    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    actor = EventActor(
        "user-1", "bot-1", "group-1", unified_msg_origin="platform:group:g1"
    )
    await subscriptions.add(
        messages.SIGN_GROUP_REPORT_SUBSCRIBE,
        origin=actor.unified_msg_origin or "",
        user_id=actor.user_id,
        group_id=actor.group_id or "",
        bot_id=actor.bot_id,
    )
    service = _service(
        database,
        FakeCheckinTransport(),
        subscriptions=subscriptions,
        group_report=False,
    )

    denied = await service.subscribe_group_report(
        _request(actor=actor, text="订阅本群签到报告")
    )
    removed = await service.subscribe_group_report(
        _request(actor=actor, text="取消订阅本群签到报告")
    )

    assert denied.text == messages.SIGN_GROUP_REPORT_DISABLED
    assert removed.text == messages.SIGN_GROUP_REPORT_UNSUBSCRIBED
    assert await subscriptions.get(messages.SIGN_GROUP_REPORT_SUBSCRIBE) == ()
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
async def test_auto_sign_skips_bindings_without_usable_credentials(tmp_path: Path) -> None:
    """计划任务不把历史绑定/缺失凭据账号计为失败，也不产生群失败明细。"""

    database = await _database_with_binding(tmp_path)
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="stale-user",
            uid="2222222222222",
            group_id="group-1",
            is_active=False,
            auto_sign_enabled=True,
        )
    service = _service(database, FakeCheckinTransport(), group_report=True)

    report = await service.auto_sign_report()

    assert "今日成功游戏签到 1 个账号" in report.summary_text
    reports = report.group_reports["group-1"]
    assert all(item.success == 1 and item.failed == 0 for item in reports)
    assert all(item.mention_details == () for item in reports)
    await database.dispose()


@pytest.mark.asyncio
async def test_group_report_ignores_reply_failure_after_community_sign(
    tmp_path: Path,
) -> None:
    """社区签到成功后，附加回复普通失败不计群失败，也不触发 @。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        task_process=_task_fixture_with_reply(),
        posts=_posts_fixture(1),
        post_ok=False,
    )
    service = _service(
        database,
        transport,
        community_tasks=("bbs_sign", "bbs_reply"),
        group_report=True,
    )

    report = await service.auto_sign_report()
    community_report = next(
        item
        for item in report.group_reports["group-1"]
        if item.report_type == "community"
    )

    assert community_report.success == 1
    assert community_report.failed == 0
    assert community_report.mention_details == ()
    await database.dispose()


@pytest.mark.asyncio
async def test_group_report_preserves_community_sign_on_reply_transport_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回复 transport 异常不能抹掉已完成的社区签到状态。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        task_process=_task_fixture_with_reply(),
        posts=_posts_fixture(1),
    )

    async def fail_reply(actor, uid, post, *, credential_user_id):
        del actor, post, credential_user_id
        transport.calls.append("do_reply")
        raise CheckinTransportError(
            CheckinFailureKind.NETWORK,
            resource="社区回复",
        )

    monkeypatch.setattr(transport, "do_reply", fail_reply)
    service = _service(
        database,
        transport,
        community_tasks=("bbs_sign", "bbs_reply"),
        group_report=True,
    )

    report = await service.auto_sign_report()
    community_report = next(
        item
        for item in report.group_reports["group-1"]
        if item.report_type == "community"
    )

    assert "do_reply" in transport.calls
    assert "今日社区签到 0 个账号" in report.summary_text
    assert community_report.success == 1
    assert community_report.failed == 0
    assert community_report.mention_details == ()
    async with database.session() as session:
        record = await SignRecordRepository.get(
            session,
            uid=UID,
            record_date=datetime.now(tz=SHANGHAI_TZ).date(),
        )
    assert record is not None
    assert record.bbs_sign == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_credential_expiry_is_not_group_failure(
    tmp_path: Path,
) -> None:
    """运行中确认凭据过期时跳过群失败 @，与原 DNAUID 行为一致。"""

    database = await _database_with_binding(tmp_path)
    transport = FakeCheckinTransport(
        fail=CheckinTransportError(
            CheckinFailureKind.CREDENTIAL,
            resource="签到日历",
        )
    )
    service = _service(database, transport, group_report=True)

    report = await service.auto_sign_report()

    assert "今日成功游戏签到 0 个账号" in report.summary_text
    assert report.group_reports == {}
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_all_preserves_text_only_compatibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兼容接口只返回全局文字，不因群报告配置触发图片渲染。"""

    database = await _database_with_binding(tmp_path)
    rendered = False

    async def render(*_args: object, **_kwargs: object) -> bytes:
        nonlocal rendered
        rendered = True
        return b"unexpected"

    monkeypatch.setattr("src.modules.checkin.service.create_sign_info_image", render)
    service = _service(
        database,
        FakeCheckinTransport(),
        group_report=True,
        group_report_image=True,
    )

    text = await service.auto_sign_all()

    assert "今日成功游戏签到 1 个账号" in text
    assert rendered is False
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_report_groups_game_and_community_by_group(
    tmp_path: Path,
) -> None:
    """自动签到报告按群拆分游戏/社区结果，私聊绑定只进入全局汇总。"""

    database = AsyncDatabase(tmp_path / "checkin.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-a",
            uid="uid-a",
            group_id="group-a",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-b",
            uid="uid-b",
            group_id="group-b",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-private",
            uid="uid-private",
            group_id=None,
            is_active=True,
        )

    transport = FakeCheckinTransport()
    original_calendar = transport.get_sign_calendar

    async def get_sign_calendar(actor, uid, *, credential_user_id):
        del actor, credential_user_id
        transport.calls.append("get_sign_calendar")
        return transport.calendar

    transport.get_sign_calendar = get_sign_calendar
    service = _service(database, transport, group_report=True)

    report = await service.auto_sign_report()

    assert set(report.group_reports) == {"group-a", "group-b"}
    assert "uid-private" not in report.group_reports
    assert "今日成功游戏签到 3 个账号" in report.summary_text
    assert "今日社区签到 3 个账号" in report.summary_text
    for group_id, uid in (("group-a", "uid-a"), ("group-b", "uid-b")):
        reports = report.group_reports[group_id]
        assert {item.report_type for item in reports} == {"game", "community"}
        assert all(item.success == 1 and item.failed == 0 for item in reports)
        assert all(item.detail_text == "" for item in reports)
        assert all(
            messages.sign_detail_separator() not in item.detail_text for item in reports
        )

    del original_calendar
    await database.dispose()


@pytest.mark.asyncio
async def test_group_report_uses_structured_details_not_display_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """群报告分类消费结构化详情，不依赖最终展示文本的行位置。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeCheckinTransport(), group_report=True)
    outcome = CheckinOutcome(
        game_status=SignStatus.DONE,
        bbs_status=SignStatus.FAILED,
        community_sign_status=SignStatus.FAILED,
        detail_lines=("展示层社区标题", "展示层误分类游戏行", "展示层误分类社区行"),
        error="社区操作失败",
        game_detail_lines=("游戏签到：已完成", "游戏奖励：5"),
        community_detail_lines=("社区点赞：失败",),
    )

    async def run_all_signs_with_results(**_kwargs: object) -> _CheckinBatchResult:
        return _CheckinBatchResult(
            summary=CheckinSummary(success=1, failed=0, game_success=1, bbs_success=0),
            group_results={"group-1": (("user-1", outcome),)},
        )

    monkeypatch.setattr(
        service, "_run_all_signs_with_results", run_all_signs_with_results
    )

    report = await service.auto_sign_report()
    reports = {item.report_type: item for item in report.group_reports["group-1"]}

    assert reports["game"].detail_text == ""
    assert reports["game"].mention_details == ()
    assert reports["community"].detail_text == ""
    assert reports["community"].mention_details == (
        (
            "user-1",
            "\n".join(
                ["社区点赞：失败", messages.sign_detail_error(outcome.error)]
            ),
        ),
    )
    assert "展示层误分类" not in reports["community"].mention_details[0][1]

    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_report_builds_only_requested_group_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只为调度器传入的订阅群生成报告及图片，避免无订阅群的渲染开销。"""

    database = await _database_with_binding(tmp_path)
    service = _service(
        database,
        FakeCheckinTransport(),
        group_report=True,
        group_report_image=True,
    )
    outcome = CheckinOutcome(
        game_status=SignStatus.DONE,
        bbs_status=SignStatus.DONE,
        game_detail_lines=("游戏签到：已完成",),
        community_detail_lines=("社区签到：已完成",),
    )

    async def run_all_signs_with_results(**_kwargs: object) -> _CheckinBatchResult:
        return _CheckinBatchResult(
            summary=CheckinSummary(success=2, failed=0, game_success=2, bbs_success=2),
            group_results={
                "group-1": (("uid-1", outcome),),
                "group-2": (("uid-2", outcome),),
            },
        )

    rendered: list[str] = []

    async def render(text: str, *, theme: str = "blue") -> bytes:
        rendered.append(theme)
        return f"image:{theme}".encode()

    monkeypatch.setattr(
        service, "_run_all_signs_with_results", run_all_signs_with_results
    )
    monkeypatch.setattr("src.modules.checkin.service.create_sign_info_image", render)

    report = await service.auto_sign_report(group_ids={"group-1"})

    assert set(report.group_reports) == {"group-1"}
    assert rendered == ["blue", "yellow"]

    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_report_group_reports_are_disabled_by_config(
    tmp_path: Path,
) -> None:
    """群组报告总开关关闭时，结构化结果不生成群报告。"""

    database = await _database_with_binding(tmp_path)
    service = _service(database, FakeCheckinTransport(), group_report=False)

    report = await service.auto_sign_report()

    assert report.group_reports == {}
    assert "今日成功游戏签到 1 个账号" in report.summary_text
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_sign_report_renders_group_images_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """图片开关只影响群组报告，并按游戏/社区使用不同主题。"""

    database = await _database_with_binding(tmp_path)
    rendered: list[tuple[str, str]] = []

    async def render(text: str, *, theme: str = "blue") -> bytes:
        rendered.append((text, theme))
        return f"image:{theme}".encode()

    monkeypatch.setattr("src.modules.checkin.service.create_sign_info_image", render)
    service = _service(
        database,
        FakeCheckinTransport(),
        group_report=True,
        group_report_image=True,
    )

    report = await service.auto_sign_report()

    group_reports = report.group_reports["group-1"]
    assert {item.report_type for item in group_reports} == {"game", "community"}
    assert {item.image_bytes for item in group_reports} == {
        b"image:blue",
        b"image:yellow",
    }
    assert [theme for _text, theme in rendered] == ["blue", "yellow"]
    assert all(text.startswith("✅[二重螺旋]") for text, _theme in rendered)
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
