"""Goal 2 / Task 07：用户级联删除协调器契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
    GroupPrivacySettingRepository,
    PrivacySettingRepository,
    SignRecordRepository,
)
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import (
    AccountDeletionCoordinator,
    AdminAccountService,
    AdminErrorCode,
)
from src.modules.notices import messages as notices_messages


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为删除协调器提供隔离 SQLite。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


async def _seed_database(database: AsyncDatabase) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1002",
            group_id="group-2",
            is_active=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            uid="1002",
            group_id="group-3",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            app_cookie="user-1-secret",
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1002",
            app_cookie="user-1-second-secret",
        )
        await CredentialRepository.add(
            session,
            user_id="user-2",
            uid="1002",
            app_cookie="user-2-secret",
        )
        await PrivacySettingRepository.add(
            session,
            user_id="user-1",
            group_id=None,
            allow_peek=False,
            uid_hidden=True,
        )
        await PrivacySettingRepository.add(
            session,
            user_id="user-1",
            group_id="group-1",
            allow_peek=False,
            uid_hidden=True,
        )
        await GroupPrivacySettingRepository.add(
            session,
            group_id="group-1",
            force_allow_peek=False,
            force_uid_hidden=True,
        )
        await SignRecordRepository.add(
            session,
            uid="1001",
            record_date=date(2026, 8, 1),
            game_sign=1,
        )
        await SignRecordRepository.add(
            session,
            uid="1002",
            record_date=date(2026, 8, 1),
            game_sign=2,
        )
        await SignRecordRepository.add(
            session,
            uid="2001",
            record_date=date(2026, 8, 1),
            game_sign=3,
        )


async def _seed_subscriptions(store: SubscriptionStore) -> None:
    await store.add(
        notices_messages.MH_SUBSCRIBE,
        origin="direct:user-1",
        user_id="user-1",
        uid="user-1",
        user_type="direct",
        extra_message="角色:角色甲",
    )
    await store.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:user-1",
        user_id="user-1",
        group_id="group-1",
        uid="user-1",
        user_type="group",
        extra_message="武器:武器甲",
    )
    await store.add(
        notices_messages.MH_SUBSCRIBE,
        origin="direct:user-2",
        user_id="user-2",
        uid="user-2",
        user_type="direct",
        extra_message="角色:角色乙",
    )
    for sub_type, origin in (
        (notices_messages.MH_PIC_SUBSCRIBE, "group:picture"),
        (notices_messages.MH_TEXT_SUBSCRIBE, "group:text"),
        (notices_messages.ANN_SUBSCRIBE, "group:announcement"),
    ):
        await store.add(
            sub_type,
            origin=origin,
            user_id="user-1",
            group_id=origin.split(":", 1)[1],
            user_type="group",
        )
    await store.add(
        "订阅二重螺旋签到结果",
        origin="group:sign-result",
        user_id="user-1",
        group_id="sign-result",
        user_type="group",
    )


def _subscription_exists(
    subscriptions: tuple[Any, ...],
    *,
    sub_type: str,
    origin: str,
) -> bool:
    return any(
        sub.type == sub_type and sub.unified_msg_origin == origin
        for sub in subscriptions
    )


@pytest.mark.asyncio
async def test_delete_user_requires_exact_confirmation_and_removes_global_scope(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_database(database)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _seed_subscriptions(subscriptions)
    coordinator = AccountDeletionCoordinator(database, subscriptions)

    preview_response = await AdminAccountService(database).preview_delete_user("user-1")
    assert preview_response.ok is True
    assert preview_response.data is not None
    plan = preview_response.data

    rejected = await coordinator.delete_user(plan, "delete:user:user-2")
    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error.code == AdminErrorCode.VALIDATION

    first = await coordinator.delete_user(plan, plan.confirmation_payload)
    assert first.ok is True
    assert first.data is not None
    assert first.data.status == "completed"
    assert first.data.step("account_bindings").count == 2
    assert first.data.step("credential_records").count == 2
    assert first.data.step("sign_records").count == 2

    async with database.session() as session:
        assert await AccountBindingRepository.list(session, user_id="user-1") == []
        assert await CredentialRepository.list(session, user_id="user-1") == []
        assert await PrivacySettingRepository.get(session, user_id="user-1") is None
        assert (
            await PrivacySettingRepository.get(
                session,
                user_id="user-1",
                group_id="group-1",
            )
            is None
        )
        assert await GroupPrivacySettingRepository.get(session, group_id="group-1") is not None
        assert await AccountBindingRepository.get(session, user_id="user-2", uid="1002") is not None
        assert await SignRecordRepository.get(session, uid="1001", record_date=date(2026, 8, 1)) is None
        assert await SignRecordRepository.get(session, uid="1002", record_date=date(2026, 8, 1)) is None
        assert await SignRecordRepository.get(session, uid="2001", record_date=date(2026, 8, 1)) is not None

    remaining = await subscriptions.list_all()
    assert not any(
        sub.type == notices_messages.MH_SUBSCRIBE and sub.user_id == "user-1"
        for sub in remaining
    )
    assert _subscription_exists(
        remaining,
        sub_type=notices_messages.MH_SUBSCRIBE,
        origin="direct:user-2",
    )
    assert _subscription_exists(
        remaining,
        sub_type=notices_messages.MH_PIC_SUBSCRIBE,
        origin="group:picture",
    )
    assert _subscription_exists(
        remaining,
        sub_type=notices_messages.ANN_SUBSCRIBE,
        origin="group:announcement",
    )

    retry = await coordinator.delete_user(plan, plan.confirmation_payload)
    assert retry.ok is True
    assert retry.data is not None
    assert retry.data.status == "completed"
    assert retry.data.step("account_bindings").status == "already_absent"
    assert retry.data.step("sign_records").status == "already_absent"


@pytest.mark.asyncio
async def test_delete_uid_forces_shared_sign_history_but_preserves_user_scope(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_database(database)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _seed_subscriptions(subscriptions)
    preview_response = await AdminAccountService(database).preview_delete_uid("user-1", "1002")
    assert preview_response.ok is True
    assert preview_response.data is not None

    response = await AccountDeletionCoordinator(database, subscriptions).delete_uid(
        preview_response.data,
        preview_response.data.confirmation_payload,
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data.status == "completed"
    async with database.session() as session:
        assert await AccountBindingRepository.get(session, user_id="user-1", uid="1002") is None
        assert await CredentialRepository.get(session, user_id="user-1", uid="1002") is None
        assert await AccountBindingRepository.get(session, user_id="user-1", uid="1001") is not None
        assert await PrivacySettingRepository.get(session, user_id="user-1") is not None
        assert await SignRecordRepository.get(session, uid="1002", record_date=date(2026, 8, 1)) is None
        assert await SignRecordRepository.get(session, uid="1001", record_date=date(2026, 8, 1)) is not None
        assert await AccountBindingRepository.get(session, user_id="user-2", uid="1002") is not None

    remaining = await subscriptions.list_all()
    assert any(
        sub.type == notices_messages.MH_SUBSCRIBE and sub.user_id == "user-1"
        for sub in remaining
    )
    assert _subscription_exists(
        remaining,
        sub_type=notices_messages.MH_PIC_SUBSCRIBE,
        origin="group:picture",
    )


@pytest.mark.asyncio
async def test_json_failure_is_partial_and_same_plan_can_retry(
    database: AsyncDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_database(database)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _seed_subscriptions(subscriptions)
    preview_response = await AdminAccountService(database).preview_delete_user("user-1")
    assert preview_response.ok is True
    assert preview_response.data is not None
    plan = preview_response.data
    coordinator = AccountDeletionCoordinator(database, subscriptions)
    original_save = subscriptions._save_unlocked
    save_attempts = 0

    def fail_once() -> None:
        nonlocal save_attempts
        save_attempts += 1
        if save_attempts == 1:
            raise OSError("simulated json storage failure")
        original_save()

    monkeypatch.setattr(subscriptions, "_save_unlocked", fail_once)
    partial = await coordinator.delete_user(plan, plan.confirmation_payload)

    assert partial.ok is False
    assert partial.error is not None and partial.error.code == AdminErrorCode.PARTIAL
    assert partial.data is not None
    assert partial.data.status == "partial"
    assert partial.data.step("personal_subscriptions").status == "failed"
    async with database.session() as session:
        assert await AccountBindingRepository.list(session, user_id="user-1") == []
    assert any(
        sub.user_id == "user-1" and sub.type == notices_messages.MH_SUBSCRIBE
        for sub in await subscriptions.list_all()
    )

    monkeypatch.setattr(subscriptions, "_save_unlocked", original_save)
    retried = await coordinator.delete_user(plan, plan.confirmation_payload)
    assert retried.ok is True
    assert retried.data is not None and retried.data.status == "completed"
    assert not any(
        sub.user_id == "user-1" and sub.type == notices_messages.MH_SUBSCRIBE
        for sub in await subscriptions.list_all()
    )


@pytest.mark.asyncio
async def test_database_failure_rolls_back_and_does_not_touch_json(
    database: AsyncDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_database(database)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await _seed_subscriptions(subscriptions)
    preview_response = await AdminAccountService(database).preview_delete_user("user-1")
    assert preview_response.ok is True
    assert preview_response.data is not None
    plan = preview_response.data
    coordinator = AccountDeletionCoordinator(database, subscriptions)
    original_delete_privacy = PrivacySettingRepository.delete_all

    async def fail_database(*args: Any, **kwargs: Any) -> int:
        del args, kwargs
        raise OSError("simulated sqlite failure")

    monkeypatch.setattr(PrivacySettingRepository, "delete_all", fail_database)
    failed = await coordinator.delete_user(plan, plan.confirmation_payload)

    assert failed.ok is False
    assert failed.error is not None and failed.error.code == AdminErrorCode.INTERNAL
    assert failed.data is not None
    assert failed.data.step("account_bindings").status == "failed"
    async with database.session() as session:
        assert await AccountBindingRepository.get(session, user_id="user-1", uid="1001") is not None
    assert any(
        sub.user_id == "user-1" and sub.type == notices_messages.MH_SUBSCRIBE
        for sub in await subscriptions.list_all()
    )

    monkeypatch.setattr(PrivacySettingRepository, "delete_all", original_delete_privacy)
    retried = await coordinator.delete_user(plan, plan.confirmation_payload)
    assert retried.ok is True
