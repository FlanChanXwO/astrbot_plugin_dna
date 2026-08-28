"""Goal 2 / Task 03：repository 与账号、隐私 service 的全局身份契约。"""

from collections.abc import AsyncIterator
from typing import cast

import pytest
import pytest_asyncio

from src.entry.event import EventActor
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
    GroupPrivacySettingRepository,
    PrivacySettingRepository,
)
from src.modules.account.contracts import AccountTransport
from src.modules.account.service import AccountService
from src.modules.privacy.service import PrivacyService


@pytest_asyncio.fixture
async def database(tmp_path) -> AsyncIterator[AsyncDatabase]:
    """为每条全局身份测试提供隔离的新 schema。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_global_repositories_share_identity_and_keep_users_isolated(database):
    """repository 按 user_id/uid 共享数据，不再按 bot_id 分裂身份。"""

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
            is_active=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1002",
            group_id="group-2",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            app_cookie="cookie-fixture",
        )
        await PrivacySettingRepository.set(
            session,
            user_id="user-1",
            group_id=None,
            allow_peek=False,
        )
        await GroupPrivacySettingRepository.set(
            session,
            group_id="group-1",
            force_uid_hidden=True,
        )

    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
        bindings = await AccountBindingRepository.list(
            session,
            user_id="user-1",
        )
        all_bindings = await AccountBindingRepository.list_all(session)
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
        privacy = await PrivacySettingRepository.get(
            session,
            user_id="user-1",
            group_id=None,
        )
        group_privacy = await GroupPrivacySettingRepository.get(
            session,
            group_id="group-1",
        )
        other_user = await AccountBindingRepository.list(
            session,
            user_id="user-2",
        )

    assert binding is not None
    assert [record.uid for record in bindings] == ["1001", "1002"]
    assert len(all_bindings) == 2
    assert credential is not None
    assert credential.app_cookie == "cookie-fixture"
    assert privacy is not None and privacy.allow_peek is False
    assert group_privacy is not None and group_privacy.force_uid_hidden is True
    assert other_user == []

    async with database.transaction() as session:
        assert await AccountBindingRepository.set_active(
            session,
            user_id="user-1",
            uid="1001",
        ) is True

    async with database.session() as session:
        current = await AccountBindingRepository.current(
            session,
            user_id="user-1",
        )
        bindings = await AccountBindingRepository.list(
            session,
            user_id="user-1",
        )

    assert current is not None and current.uid == "1001"
    assert [(record.uid, record.is_active) for record in bindings] == [
        ("1001", True),
        ("1002", False),
    ]


@pytest.mark.asyncio
async def test_account_service_reads_global_accounts_from_another_bot(database):
    """账号 service 在不同 Bot 事件下读取同一用户的绑定和凭据。"""

    service = AccountService(
        database,
        cast(AccountTransport, object()),
        max_bind_count=3,
    )
    first_bot = EventActor(user_id="user-1", bot_id="bot-1", group_id="group-1")
    second_bot = EventActor(user_id="user-1", bot_id="bot-2", group_id="group-2")
    other_user = EventActor(user_id="user-2", bot_id="bot-2", group_id="group-2")

    assert "绑定成功" in (await service.bind_uid(first_bot, "1234567890123")).text
    assert "绑定成功" in (await service.bind_uid(second_bot, "2234567890123")).text

    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-global-fixture",
        )

    listing = await service.list_bindings(second_bot)
    credentials = await service.credentials(second_bot)
    other_listing = await service.list_bindings(other_user)

    assert "1234567890123" in listing.text and "2234567890123" in listing.text
    assert "1234567890123" in credentials.text
    assert "已保存" in credentials.text
    assert other_listing.text == "当前没有已绑定的UID！"

    switched = await service.switch_uid(second_bot, "1234567890123")
    assert switched.text == "UID切换成功！"
    async with database.session() as session:
        current = await AccountBindingRepository.current(session, user_id="user-1")
    assert current is not None and current.uid == "1234567890123"


@pytest.mark.asyncio
async def test_privacy_service_shares_personal_and_group_policy_across_bots(database):
    """隐私 service 在不同 Bot 事件下读取同一用户和群组策略。"""

    service = PrivacyService(database)
    first_bot = EventActor(user_id="user-1", bot_id="bot-1", group_id="group-1")
    second_bot = EventActor(user_id="user-1", bot_id="bot-2", group_id="group-1")

    await service.set_personal_peek(first_bot, False)
    await service.set_personal_uid_hidden(first_bot, True)

    assert await service.is_peek_allowed("user-1", group_id="group-1") is False
    assert await service.is_uid_hidden("user-1", group_id="group-1") is True
    assert await service.is_peek_allowed("user-2", group_id="group-1") is True

    await service.set_group_peek(second_bot, True)
    await service.set_group_uid_hidden(second_bot, False)
    assert await service.is_peek_allowed("user-1", group_id="group-1") is True
    assert await service.is_uid_hidden("user-1", group_id="group-1") is False

    await service.cancel_group_peek(first_bot)
    await service.cancel_group_uid_hidden(first_bot)
    snapshot = await service.get_privacy_setting("user-1", group_id=None)
    assert snapshot.allow_peek is False
    assert snapshot.uid_hidden is True
