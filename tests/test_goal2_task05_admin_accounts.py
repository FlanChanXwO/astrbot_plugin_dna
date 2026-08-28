"""Goal 2 / Task 05：Admin 账号管理服务与明文凭据 DTO。"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.modules.admin import (
    AdminAccountService,
    AdminAccountUpdate,
    CredentialPayload,
)


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为管理账号测试提供隔离数据库。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


def _payload(prefix: str = "one") -> CredentialPayload:
    """构造包含全部 App/Web 字段的管理凭据 DTO。"""

    return CredentialPayload(
        app_cookie=f"{prefix}-app-cookie-secret",
        app_device_code=f"{prefix}-app-device-secret",
        app_d_num=f"{prefix}-app-d-num-secret",
        app_refresh_token=f"{prefix}-app-refresh-secret",
        app_status=f"{prefix}-app-status",
        web_token=f"{prefix}-web-token-secret",
        web_device_code=f"{prefix}-web-device-secret",
        web_d_num=f"{prefix}-web-d-num-secret",
        web_refresh_token=f"{prefix}-web-refresh-secret",
        web_status=f"{prefix}-web-status",
    )


async def _seed_account(
    database: AsyncDatabase,
    *,
    user_id: str = "user-1",
    uid: str = "1001",
    group_id: str | None = "group-1",
    is_active: bool = True,
    payload: CredentialPayload | None = None,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            group_id=group_id,
            is_active=is_active,
        )
        if payload is not None:
            await CredentialRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                **payload.to_plaintext_dict(),
            )


def test_credential_payload_is_complete_but_redacted_by_default() -> None:
    payload = _payload()
    rendered = f"{payload!r} {payload}"

    assert set(payload.to_plaintext_dict()) == {
        "app_cookie",
        "app_device_code",
        "app_d_num",
        "app_refresh_token",
        "app_status",
        "web_token",
        "web_device_code",
        "web_d_num",
        "web_refresh_token",
        "web_status",
    }
    assert payload.to_plaintext_dict()["app_cookie"] == "one-app-cookie-secret"
    assert "one-app-cookie-secret" not in rendered
    assert "one-web-token-secret" not in rendered
    assert "one-app-status" in rendered
    assert payload.has_app_credentials is True
    assert payload.has_web_credentials is True


@pytest.mark.asyncio
async def test_list_accounts_returns_global_status_and_no_store_response(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=_payload())
    await _seed_account(
        database,
        user_id="user-2",
        uid="2001",
        group_id=None,
        payload=None,
    )

    response = await AdminAccountService(database).list_accounts()

    assert response.ok is True
    assert response.error is None
    assert response.cache_control == "no-store"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data is not None
    assert [(account.user_id, account.uid) for account in response.data] == [
        ("user-1", "1001"),
        ("user-2", "2001"),
    ]
    assert response.data[0].has_app_credentials is True
    assert response.data[0].credentials is None
    assert response.data[1].has_app_credentials is False


@pytest.mark.asyncio
async def test_account_detail_and_update_expose_all_credentials_only_explicitly(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=_payload())
    service = AdminAccountService(database)
    replacement = _payload("two")

    before = await service.get_account("user-1", "1001")
    updated = await service.update_account(
        "user-1",
        "1001",
        AdminAccountUpdate(
            group_id="group-2",
            is_active=False,
            credentials=replacement,
        ),
    )

    assert before.ok is True
    assert before.data is not None and before.data.credentials is not None
    assert before.data.credentials.to_plaintext_dict() == _payload().to_plaintext_dict()
    assert updated.ok is True
    assert updated.cache_control == "no-store"
    assert updated.data is not None
    assert updated.data.group_id == "group-2"
    assert updated.data.is_active is False
    assert updated.data.credentials is not None
    assert updated.data.credentials.to_plaintext_dict() == replacement.to_plaintext_dict()

    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
    assert binding is not None and binding.group_id == "group-2"
    assert binding.is_active is False
    assert credential is not None
    assert credential.app_cookie == "two-app-cookie-secret"
    assert credential.web_refresh_token == "two-web-refresh-secret"


@pytest.mark.asyncio
async def test_duplicate_update_is_idempotent_and_does_not_create_rows(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=_payload())
    service = AdminAccountService(database)
    update = AdminAccountUpdate(group_id="group-1", is_active=True, credentials=_payload())

    first = await service.update_account("user-1", "1001", update)
    second = await service.update_account("user-1", "1001", update)

    assert first.ok is True
    assert second.ok is True
    async with database.session() as session:
        bindings = await AccountBindingRepository.list(session, user_id="user-1")
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
    assert len(bindings) == 1
    assert credential is not None
    assert credential.app_cookie == "one-app-cookie-secret"


@pytest.mark.asyncio
async def test_active_validation_keeps_one_active_and_reports_unknown_target(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=_payload())
    await _seed_account(
        database,
        uid="1002",
        is_active=False,
        payload=None,
    )
    service = AdminAccountService(database)

    switched = await service.update_account(
        "user-1",
        "1002",
        AdminAccountUpdate(is_active=True),
    )
    disabled = await service.update_account(
        "user-1",
        "1002",
        AdminAccountUpdate(is_active=False),
    )
    missing = await service.update_account(
        "user-1",
        "9999",
        AdminAccountUpdate(is_active=True),
    )

    assert switched.ok is True
    assert disabled.ok is True
    assert missing.ok is False
    assert missing.error is not None and missing.error.code == "not_found"
    async with database.session() as session:
        bindings = await AccountBindingRepository.list(session, user_id="user-1")
    assert [(binding.uid, binding.is_active) for binding in bindings] == [
        ("1001", False),
        ("1002", False),
    ]


@pytest.mark.asyncio
async def test_identity_mutation_and_unknown_credential_edit_are_rejected(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=None)
    service = AdminAccountService(database)

    identity_conflict = await service.update_account(
        "user-1",
        "1001",
        AdminAccountUpdate(user_id="other-user", credentials=_payload("new")),
    )
    unknown = await service.update_account(
        "user-2",
        "2001",
        AdminAccountUpdate(credentials=_payload("unknown")),
    )

    assert identity_conflict.ok is False
    assert identity_conflict.error is not None
    assert identity_conflict.error.code == "conflict"
    assert unknown.ok is False
    assert unknown.error is not None and unknown.error.code == "not_found"
    async with database.session() as session:
        assert await AccountBindingRepository.get(
            session,
            user_id="user-2",
            uid="2001",
        ) is None
        assert await CredentialRepository.get(
            session,
            user_id="user-2",
            uid="2001",
        ) is None


@pytest.mark.asyncio
async def test_delete_previews_describe_scope_without_mutating_database(
    database: AsyncDatabase,
) -> None:
    await _seed_account(database, payload=_payload())
    await _seed_account(database, uid="1002", is_active=False, payload=None)
    service = AdminAccountService(database)

    uid_preview = await service.preview_delete_uid("user-1", "1001")
    user_preview = await service.preview_delete_user("user-1")

    assert uid_preview.ok is True
    assert uid_preview.data is not None
    assert uid_preview.data.affected_uids == ("1001",)
    assert "credential_records" in uid_preview.data.delete_resources
    assert uid_preview.data.requires_confirmation is True
    assert user_preview.ok is True
    assert user_preview.data is not None
    assert user_preview.data.affected_uids == ("1001", "1002")
    assert "sign_records" in user_preview.data.delete_resources
    assert "group_privacy" in user_preview.data.preserve_resources
    assert uid_preview.cache_control == "no-store"

    async with database.session() as session:
        bindings = await AccountBindingRepository.list(session, user_id="user-1")
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            uid="1001",
        )
    assert len(bindings) == 2
    assert credential is not None
