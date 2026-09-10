"""群聊社区签到报告的部分任务失败回归测试。"""

from pathlib import Path

import pytest

from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.infrastructure.rendering import CheckinRenderer
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.checkin.contracts import (
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


class _PartialFailureTransport:
    """社区签到成功，但回复任务持续失败的最小 transport。"""

    calendar = SignCalendar(
        today_signed=False,
        user_gold=0,
        signin_time=0,
        day_awards=(
            DayAward(
                award_id=1,
                period_id=1,
                day_in_period=1,
                award_name="测试奖励",
                award_num=1,
            ),
        ),
        period=SignPeriod(
            period_id=1,
            name="测试周期",
            over_days=1,
            start_date=0,
            end_date=0,
        ),
        role_info=SignRoleInfo(role_id="1", role_name="测试角色", level=1),
    )
    task_process = TaskProcess(
        daily_tasks=(
            CommunityTask(
                mark_name="bbs_sign",
                remark="签到",
                complete_times=0,
                times=1,
            ),
            CommunityTask(
                mark_name="bbs_reply",
                remark="回复",
                complete_times=0,
                times=5,
            ),
        )
    )
    posts = tuple(
        CommunityPost(post_id=f"post-{index}", payload={"postId": f"post-{index}"})
        for index in range(4)
    )

    async def get_sign_calendar(self, actor, uid, *, credential_user_id):
        return self.calendar

    async def game_sign(self, actor, uid, award, *, credential_user_id):
        return SignStatus.DONE

    async def get_task_process(self, actor, uid, *, credential_user_id):
        return self.task_process

    async def bbs_sign(self, actor, uid, *, credential_user_id):
        return SignStatus.DONE

    async def get_post_list(self, actor, uid, *, credential_user_id):
        return self.posts

    async def do_reply(self, actor, uid, post, *, credential_user_id):
        return False


class _TransportErrorAfterCommunitySignTransport(_PartialFailureTransport):
    """社区签到成功后，回复接口抛出 transport 异常。"""

    async def do_reply(self, actor, uid, post, *, credential_user_id):
        raise CheckinTransportError(
            CheckinFailureKind.NETWORK,
            resource="社区回复",
        )


async def _service_with_binding(
    tmp_path: Path,
    transport: _PartialFailureTransport,
) -> tuple[AsyncDatabase, CheckinService]:
    database = AsyncDatabase(tmp_path / "checkin.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="test-token",
            app_device_code="test-device",
        )

    service = CheckinService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=True),
        CheckinRenderer(
            tmp_path / "rendered",
            EncyclopediaResourceStore.from_root(tmp_path / "resources"),
        ),
        community_tasks=("bbs_sign", "bbs_reply"),
        group_report=True,
    )
    return database, service


@pytest.mark.asyncio
async def test_group_report_does_not_mention_when_only_reply_task_fails(
    tmp_path: Path,
) -> None:
    """社区签到成功后，附加回复失败不计群失败，也不应触发 @。"""

    database, service = await _service_with_binding(tmp_path, _PartialFailureTransport())

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
async def test_group_report_preserves_community_sign_when_reply_transport_raises(
    tmp_path: Path,
) -> None:
    """社区签到成功后，回复 transport 异常也不应计群失败或触发 @。"""

    database, service = await _service_with_binding(
        tmp_path,
        _TransportErrorAfterCommunitySignTransport(),
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
