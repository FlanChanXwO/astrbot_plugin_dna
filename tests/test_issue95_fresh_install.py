"""Issue #95 回归：全新安装的数据库必须能支撑账号、登录、签到和密函。

这些用例故意不调用 ``create_schema_for_tests()``，而是走生产 ``DatabaseMigration``。
如果有人删掉启动期 migration 或退回 ``create_all``，账号页面会重新出现
``no such table: account_bindings``，本文件会立即失败。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from src.entry.event import EventActor
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
    DatabaseMigration,
)
from src.infrastructure.persistence.migrations import default_plugin_root
from src.modules.account.contracts import (
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
)
from src.modules.account.service import AccountService
from src.modules.admin import AdminAccountService, AdminPagination

UID = "1234567890123"


@pytest_asyncio.fixture
async def migrated_database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """只通过生产 migration 建立 schema 的全新数据库。"""

    database = AsyncDatabase(tmp_path / "db" / "dna.sqlite3")
    database.path.parent.mkdir(parents=True, exist_ok=True)
    migration = DatabaseMigration(database, plugin_root=default_plugin_root())
    await migration.initialize()
    try:
        yield database
    finally:
        await database.dispose()


class FakeAccountTransport:
    """返回固定成功结果的假账号 transport，不触碰网络。"""

    def __init__(self, result: LoginResult) -> None:
        self.result = result
        self.attempts: list[LoginAttempt] = []

    async def authenticate(self, attempt: LoginAttempt) -> LoginResult:
        self.attempts.append(attempt)
        return self.result

    async def begin_login(self, actor: EventActor) -> str:
        return "https://login.test/session"

    async def request_sms_code(
        self,
        mobile: str,
        validation: str,
        dev_code: str,
    ) -> None:
        del mobile, validation, dev_code


class FakeCheckinTransport:
    """只读取已保存绑定的假签到 transport。"""

    def __init__(self) -> None:
        self.credential_user_ids: list[str] = []

    async def get_sign_calendar(self, actor, uid, *, credential_user_id):
        from src.modules.checkin.contracts import SignCalendar

        self.credential_user_ids.append(credential_user_id)
        return SignCalendar(today_signed=True)

    async def game_sign(self, actor, uid, award, *, credential_user_id):
        from src.modules.checkin.contracts import SignStatus

        return SignStatus.DONE

    async def get_task_process(self, actor, uid, *, credential_user_id):
        from src.modules.checkin.contracts import TaskProcess

        return TaskProcess()

    async def bbs_sign(self, actor, uid, *, credential_user_id):
        from src.modules.checkin.contracts import SignStatus

        return SignStatus.DONE


@pytest.mark.asyncio
async def test_fresh_runtime_database_allows_admin_account_listing(
    migrated_database: AsyncDatabase,
) -> None:
    """Dashboard「账号与预览」对空库返回正常空列表，而不是 OperationalError。"""

    response = await AdminAccountService(migrated_database).list_accounts_page(
        AdminPagination()
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data.items == ()
    assert response.data.total == 0


@pytest.mark.asyncio
async def test_fresh_runtime_database_serves_admin_accounts_http_200(
    migrated_database: AsyncDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理页会计路由对全新数据库返回 HTTP 200。"""

    from src.entry import admin_web

    monkeypatch.setattr(
        admin_web,
        "request",
        type(
            "Request",
            (),
            {"username": "dashboard-admin", "query": {"page": "1"}},
        )(),
    )
    adapter = admin_web.AdminWebAdapter(
        {"admin_account_service": AdminAccountService(migrated_database)}
    )

    response = await adapter.list_accounts()

    assert response.status_code == 200
    assert json.loads(response.body)["data"]["items"] == []


@pytest.mark.asyncio
async def test_fake_verification_login_persists_identity_and_credentials(
    migrated_database: AsyncDatabase,
) -> None:
    """Issue #95 主回归：验证码登录成功后角色与 App 凭据必须落库。"""

    cookie = "cookie-issue95-fixture"
    refresh_token = "refresh-issue95-fixture"
    service = AccountService(
        migrated_database,
        FakeAccountTransport(
            LoginResult.success(
                LoginCredentials(
                    channel=LoginChannel.APP,
                    token=cookie,
                    dev_code="device-issue95-fixture",
                    refresh_token=refresh_token,
                ),
                roles=(RoleInfo(uid=UID, name="测试角色", is_default=True),),
            )
        ),
        max_bind_count=2,
    )

    response = await service.login(
        EventActor(user_id="user-1", bot_id="bot-1", group_id="group-1"),
        LoginAttempt.from_token(cookie),
    )

    assert "登录成功" in response.text
    assert cookie not in response.text
    assert "登录服务请求失败" not in response.text

    async with migrated_database.session() as session:
        binding = await AccountBindingRepository.current(session, user_id="user-1")
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            uid=UID,
        )
    assert binding is not None
    assert binding.uid == UID
    assert binding.is_active is True
    assert credential is not None
    assert credential.app_cookie == cookie
    assert credential.app_device_code == "device-issue95-fixture"
    assert credential.app_refresh_token == refresh_token


@pytest.mark.asyncio
async def test_auto_sign_plan_reads_migrated_binding_and_credentials(
    migrated_database: AsyncDatabase,
) -> None:
    """自动签到计划能从迁移后的 schema 读到启用绑定的 App 凭据。"""

    from src.modules.checkin.service import CheckinService
    from src.modules.privacy import PrivacyService

    async with migrated_database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            group_id="group-1",
            auto_sign_enabled=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            app_cookie="cookie-issue95-fixture",
            app_device_code="device-issue95-fixture",
            app_status="有效",
        )

    transport = FakeCheckinTransport()
    service = CheckinService(
        migrated_database,
        transport,
        PrivacyService(migrated_database, allow_mention_query=False),
        renderer=None,
        community_tasks=(),
    )

    summary = await service._run_all_signs(respect_auto_sign=True)

    assert summary.success == 1
    assert summary.failed == 0
    assert transport.credential_user_ids == ["user-1"]


@pytest.mark.asyncio
async def test_auto_sign_plan_skips_bindings_disabled_after_migration(
    migrated_database: AsyncDatabase,
) -> None:
    """迁移后新增的 auto_sign_enabled 列必须真正参与筛选。"""

    async with migrated_database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            auto_sign_enabled=False,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            app_cookie="cookie-issue95-fixture",
            app_device_code="device-issue95-fixture",
            app_status="有效",
        )

    async with migrated_database.session() as session:
        candidates = await AccountBindingRepository.list_auto_sign_candidates(session)
    assert candidates == []


@pytest.mark.asyncio
async def test_secret_letter_reads_migrated_credentials(
    migrated_database: AsyncDatabase,
) -> None:
    """密函凭据解析在迁移后的 schema 上正常工作，不出现缺表错误。"""

    from src.infrastructure.http.notices import DnaApiNoticesTransport
    from src.modules.notices.contracts import NoticesTransportError

    async with migrated_database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            group_id="group-1",
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid=UID,
            app_cookie="cookie-issue95-fixture",
            app_device_code="device-issue95-fixture",
            app_status="有效",
        )

    transport = DnaApiNoticesTransport(migrated_database)
    # 不触碰真实上游；这里只验证凭据解析不经过缺表路径。
    user = await transport._legacy_user(
        EventActor("user-1", "bot-1", "group-1"),
        UID,
        "user-1",
    )
    assert user.uid == UID
    assert user.cookie == "cookie-issue95-fixture"

    # 缺凭据时必须返回稳定的 typed 错误，而不是 sqlite3.OperationalError。
    with pytest.raises(NoticesTransportError):
        await transport._legacy_user(
            EventActor("user-2", "bot-1", "group-1"),
            UID,
            "user-2",
        )
