"""T04 账号绑定、个人自动签到和 scheduler Red 契约。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio

from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.account import messages as account_messages
from src.modules.account.contracts import (
    AccountActor,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
)
from src.modules.account.service import AccountService
from src.modules.checkin import messages as checkin_messages
from src.modules.checkin.contracts import (
    CheckinCommandRequest,
    CheckinOutcome,
    SignStatus,
)
from src.modules.checkin.service import CheckinService


UID_ONE = "1234567890123"
UID_TWO = "2234567890123"
UID_THREE = "3234567890123"


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为 T04 每条契约提供隔离的 rewrite SQLite。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


def _account_actor() -> AccountActor:
    return AccountActor(user_id="user-1", bot_id="bot-1", group_id="group-1")


def _event_actor() -> EventActor:
    return EventActor(user_id="user-1", bot_id="bot-1", group_id="group-1")


def _login_result(*roles: RoleInfo) -> LoginResult:
    return LoginResult.success(
        LoginCredentials(
            channel=LoginChannel.APP,
            token="t04-app-token",
            dev_code="t04-device-code",
        ),
        roles=tuple(roles),
    )


def _checkin_request(actor: EventActor | None = None) -> CheckinCommandRequest:
    return CheckinCommandRequest(
        actor=actor or _event_actor(),
        target_user_id=None,
        text="全部签到",
    )


@pytest.mark.asyncio
async def test_first_login_uses_configured_default_auto_sign_value(
    database: AsyncDatabase,
) -> None:
    """首个 UID 绑定应使用 sign_in.default_auto_sign_enabled。"""

    service = AccountService(
        database,
        object(),
        max_bind_count=2,
        default_auto_sign_enabled=False,
    )

    response = await service.complete_login(
        _account_actor(),
        _login_result(RoleInfo(uid=UID_ONE, is_default=True)),
    )

    assert isinstance(response, PlainTextResponse)
    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid=UID_ONE,
        )
    assert binding is not None
    assert binding.auto_sign_enabled is False


@pytest.mark.asyncio
async def test_relogin_preserves_existing_auto_sign_choice(
    database: AsyncDatabase,
) -> None:
    """重新登录只更新凭据，不覆盖用户已经保存的自动签到选择。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_ONE,
            group_id="group-1",
            is_active=True,
            auto_sign_enabled=False,
        )

    service = AccountService(
        database,
        object(),
        max_bind_count=2,
        default_auto_sign_enabled=True,
    )
    await service.complete_login(
        _account_actor(),
        _login_result(RoleInfo(uid=UID_ONE, is_default=True)),
    )

    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid=UID_ONE,
        )
    assert binding is not None
    assert binding.auto_sign_enabled is False


@pytest.mark.asyncio
async def test_user_can_disable_and_reenable_auto_sign_for_current_uid(
    database: AsyncDatabase,
) -> None:
    """个人关闭后仍可显式重新开启，且状态按 UID 持久化。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_ONE,
            group_id="group-1",
            is_active=True,
            auto_sign_enabled=True,
        )

    service = CheckinService(database, object(), object(), object())
    request = _checkin_request()

    disabled = await service.set_auto_sign(request, enabled=False)
    enabled = await service.set_auto_sign(request, enabled=True)

    assert disabled.text == checkin_messages.CHECKIN_AUTO_DISABLED
    assert enabled.text == checkin_messages.CHECKIN_AUTO_ENABLED
    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid=UID_ONE,
        )
    assert binding is not None
    assert binding.auto_sign_enabled is True


@pytest.mark.asyncio
async def test_manual_all_sign_ignores_personal_auto_sign_switch(
    database: AsyncDatabase,
) -> None:
    """管理员手动全部签到必须包含已关闭自动签到的 UID。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_ONE,
            group_id="group-1",
            is_active=True,
            auto_sign_enabled=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            uid=UID_TWO,
            group_id="group-2",
            is_active=True,
            auto_sign_enabled=True,
        )

    service = CheckinService(database, object(), object(), object())
    calls: list[str] = []

    async def fake_sign_one(
        _actor: EventActor,
        uid: str,
        _credential_user_id: str,
    ) -> CheckinOutcome:
        calls.append(uid)
        return CheckinOutcome(SignStatus.DONE, SignStatus.DONE)

    service._sign_one = fake_sign_one  # type: ignore[method-assign]
    response = await service.sign_all(_checkin_request())

    assert set(calls) == {UID_ONE, UID_TWO}
    assert isinstance(response, PlainTextResponse)
    assert account_messages.UID_BIND_LIMIT not in response.text


@pytest.mark.asyncio
async def test_bind_uid_obeys_per_user_limit_without_deleting_existing_bindings(
    database: AsyncDatabase,
) -> None:
    """新增 UID 超过用户上限时拒绝本次操作并保留已有绑定。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_ONE,
            group_id="group-1",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_TWO,
            group_id="group-1",
            is_active=False,
        )

    service = AccountService(database, object(), max_bind_count=2)
    response = await service.bind_uid(_account_actor(), UID_THREE)

    assert response.text == account_messages.UID_BIND_LIMIT
    async with database.session() as session:
        bindings = await AccountBindingRepository.list(session, user_id="user-1")
    assert [binding.uid for binding in bindings] == [UID_ONE, UID_TWO]


@pytest.mark.asyncio
async def test_concurrent_same_uid_bind_requests_keep_one_binding(
    database: AsyncDatabase,
) -> None:
    """并发首登同一 UID 时必须依赖唯一性/事务保证只落一条绑定。"""

    service = AccountService(database, object(), max_bind_count=2)
    actor = _account_actor()

    responses = await asyncio.gather(
        service.bind_uid(actor, UID_ONE),
        service.bind_uid(actor, UID_ONE),
    )

    assert {response.text for response in responses} <= {
        account_messages.UID_BIND_SUCCESS,
        account_messages.UID_BIND_DUPLICATE,
    }
    async with database.session() as session:
        bindings = await AccountBindingRepository.list(session, user_id="user-1")
    assert len(bindings) == 1
    assert bindings[0].uid == UID_ONE


@pytest.mark.asyncio
async def test_scheduler_skips_uids_with_auto_sign_disabled(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    """scheduler 只执行个人开关开启的 UID，不因全局任务存在而强制签到。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID_ONE,
            group_id="group-1",
            is_active=True,
            auto_sign_enabled=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            uid=UID_TWO,
            group_id="group-2",
            is_active=True,
            auto_sign_enabled=True,
        )

    service = CheckinService(database, object(), object(), object())
    calls: list[str] = []

    async def fake_sign_one(
        _actor: EventActor,
        uid: str,
        _credential_user_id: str,
    ) -> CheckinOutcome:
        calls.append(uid)
        return CheckinOutcome(SignStatus.DONE, SignStatus.DONE)

    service._sign_one = fake_sign_one  # type: ignore[method-assign]
    scheduler = SignScheduler(
        service,
        SubscriptionStore(tmp_path / "subscriptions.json"),
    )

    await scheduler.run_sign_once()

    assert calls == [UID_TWO]


class _NoGlobalFlagCheckin:
    """只接受个人状态筛选后的自动签到接口，不接受全局强制开关。"""

    def __init__(self) -> None:
        self.calls = 0

    async def auto_sign_all(self) -> str:
        self.calls += 1
        return "personal-choice-summary"

    async def clear_sign_records_before(self, _record_date: date) -> int:
        return 0


@pytest.mark.asyncio
async def test_scheduler_calls_personal_choice_auto_sign_without_global_override(
    tmp_path: Path,
) -> None:
    """scheduler 不得再用 enable_all_users 改写每个 UID 的选择。"""

    checkin = _NoGlobalFlagCheckin()
    scheduler = SignScheduler(
        checkin,
        SubscriptionStore(tmp_path / "subscriptions.json"),
    )

    text = await scheduler.run_sign_once()

    assert text == "personal-choice-summary"
    assert checkin.calls == 1
