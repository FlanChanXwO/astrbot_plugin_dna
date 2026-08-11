"""Task 10 账号 use case、transport 错误和敏感信息边界测试。"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from src.infrastructure.http.account import (
    AccountTransportError,
    DnaApiAccountTransport,
    TransportErrorKind,
)
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.modules.account.contracts import (
    AccountActor,
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
)
from src.modules.account.service import AccountService, parse_login_attempt


@pytest_asyncio.fixture
async def database(tmp_path) -> AsyncIterator[AsyncDatabase]:
    """为每条账号测试提供隔离新 SQLite。"""
    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


class FakeAccountTransport:
    """可控制成功、取消和错误分支的 transport fixture。"""

    def __init__(self, outcome: object, page_url: str = "https://login.test/session") -> None:
        self.outcome = outcome
        self.page_url = page_url
        self.attempts: list[LoginAttempt] = []
        self.actors: list[AccountActor] = []

    async def begin_login(self, actor: AccountActor) -> str:
        self.actors.append(actor)
        if isinstance(self.outcome, AccountTransportError):
            raise self.outcome
        return self.page_url

    async def authenticate(self, attempt: LoginAttempt) -> LoginResult:
        self.attempts.append(attempt)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        assert isinstance(self.outcome, LoginResult)
        return self.outcome


def _actor() -> AccountActor:
    return AccountActor(user_id="user-1", bot_id="bot-1", group_id="group-1")


@pytest.mark.asyncio
async def test_login_success_persists_roles_and_credentials_without_leaking_secrets(database):
    """登录成功应原子保存凭据和角色绑定，响应不得包含任何 secret。"""
    app_cookie = "cookie-task10-fixture"
    refresh_token = "refresh-task10-fixture"
    transport = FakeAccountTransport(
        LoginResult.success(
            LoginCredentials(
                channel=LoginChannel.APP,
                token=app_cookie,
                dev_code="device-task10-fixture",
                refresh_token=refresh_token,
            ),
            roles=(RoleInfo(uid="1234567890123", name="测试角色", is_default=True),),
        )
    )
    service = AccountService(database, transport, max_bind_count=2)

    response = await service.login(_actor(), LoginAttempt.from_token(app_cookie))

    assert "登录成功" in response.text
    assert "测试角色" in response.text
    assert app_cookie not in response.text
    assert refresh_token not in response.text
    assert transport.attempts[0].token == app_cookie

    async with database.session() as session:
        binding = await AccountBindingRepository.get(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
        )
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
        )
    assert binding is not None
    assert binding.is_active is True
    assert credential is not None
    assert credential.app_cookie == app_cookie
    assert credential.app_refresh_token == refresh_token
    assert app_cookie not in repr(credential)


@pytest.mark.asyncio
async def test_login_default_role_becomes_current_even_when_bindings_exist(database):
    """重复登录时沿用 legacy：服务端默认角色切换为当前 UID。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
            group_id="group-1",
            is_active=True,
        )

    transport = FakeAccountTransport(
        LoginResult.success(
            LoginCredentials(
                channel=LoginChannel.APP,
                token="cookie-default-role-fixture",
                dev_code="device-default-role-fixture",
            ),
            roles=(
                RoleInfo(uid="1234567890123", name="旧当前角色"),
                RoleInfo(uid="2234567890123", name="默认角色", is_default=True),
            ),
        ),
    )
    service = AccountService(database, transport, max_bind_count=3)

    response = await service.login(
        _actor(),
        LoginAttempt.from_token("token-default-role-fixture"),
    )

    assert "登录成功" in response.text
    assert response.text.index("2234567890123") < response.text.index("1234567890123")
    async with database.session() as session:
        bindings = await AccountBindingRepository.list(
            session,
            user_id="user-1",
            bot_id="bot-1",
        )
    assert [(binding.uid, binding.is_active) for binding in bindings] == [
        ("1234567890123", False),
        ("2234567890123", True),
    ]


@pytest.mark.asyncio
async def test_login_rolls_back_bindings_when_credential_write_fails(database, monkeypatch):
    """凭据写入异常时，登录事务不得留下孤立绑定。"""
    transport = FakeAccountTransport(
        LoginResult.success(
            LoginCredentials(
                channel=LoginChannel.APP,
                token="cookie-rollback-fixture",
                dev_code="device-rollback-fixture",
            ),
            roles=(RoleInfo(uid="1234567890123", name="事务角色"),),
        ),
    )

    async def fail_save_app(*_args, **_kwargs):
        raise RuntimeError("credential-write-fixture")

    monkeypatch.setattr(CredentialRepository, "save_app", fail_save_app)
    service = AccountService(database, transport, max_bind_count=2)

    with pytest.raises(RuntimeError, match="credential-write-fixture"):
        await service.login(
            _actor(),
            LoginAttempt.from_token("token-rollback-fixture"),
        )

    async with database.session() as session:
        assert await AccountBindingRepository.list(
            session,
            user_id="user-1",
            bot_id="bot-1",
        ) == []
        assert await CredentialRepository.list(
            session,
            user_id="user-1",
            bot_id="bot-1",
        ) == []


@pytest.mark.asyncio
async def test_login_page_start_and_cancel_are_framework_free(database):
    """登录页 URL 和用户取消均由 transport 结果转换为安全 DTO。"""
    transport = FakeAccountTransport(LoginResult.cancelled())
    service = AccountService(database, transport, max_bind_count=2)

    page_response = await service.begin_login(_actor())
    cancelled_response = await service.login(
        _actor(),
        LoginAttempt.from_sms("13800138000", "1234"),
    )

    assert page_response.text == "登录地址：https://login.test/session"
    assert cancelled_response.text == "登录已取消"
    assert transport.actors == [_actor()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        (TransportErrorKind.NETWORK, "网络"),
        (TransportErrorKind.STATUS, "状态"),
        (TransportErrorKind.SERVER, "服务端"),
    ),
)
async def test_login_transport_errors_are_visible_but_do_not_leak_details(
    database,
    kind: TransportErrorKind,
    expected: str,
):
    """网络、状态码和服务端失败不得伪装成功，也不得回显 transport detail。"""
    secret_detail = "token=secret-task10-detail"
    transport = FakeAccountTransport(AccountTransportError(kind, detail=secret_detail, status_code=502))
    service = AccountService(database, transport, max_bind_count=2)

    response = await service.login(
        _actor(),
        LoginAttempt.from_token("token-task10-input"),
    )

    assert expected in response.text
    assert "登录成功" not in response.text
    assert secret_detail not in response.text
    error = transport.outcome
    assert isinstance(error, AccountTransportError)
    assert secret_detail not in str(error)
    assert secret_detail not in repr(error)
    async with database.session() as session:
        assert (
            await AccountBindingRepository.get(
                session,
                user_id="user-1",
                bot_id="bot-1",
                uid="1234567890123",
            )
            is None
        )


@pytest.mark.asyncio
async def test_bind_switch_delete_logout_lifecycle_uses_normalized_records(database):
    """绑定、切换、删除和退出均在同一事务边界内维护当前 UID。"""
    transport = FakeAccountTransport(LoginResult.cancelled())
    service = AccountService(database, transport, max_bind_count=2)

    first = await service.bind_uid(_actor(), "1234567890123")
    second = await service.bind_uid(_actor(), "2234567890123")
    switched = await service.switch_uid(_actor(), "2234567890123")
    duplicate = await service.bind_uid(_actor(), "2234567890123")

    assert "绑定成功" in first.text
    assert "绑定成功" in second.text
    assert switched.text == "UID切换成功！"
    assert duplicate.text == "该UID已经绑定过了！"

    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="2234567890123",
            app_cookie="cookie-logout-fixture",
            app_device_code="device-logout-fixture",
        )

    logout = await service.logout(_actor())
    assert logout.text == "成功退出登录"

    deleted = await service.delete_uid(_actor(), "1234567890123")
    assert deleted.text == "UID删除成功！"
    async with database.session() as session:
        assert (
            await AccountBindingRepository.get(
                session,
                user_id="user-1",
                bot_id="bot-1",
                uid="1234567890123",
            )
            is None
        )


@pytest.mark.asyncio
async def test_credential_query_returns_status_summary_not_raw_tokens(database):
    """凭据查询只返回可用状态，不把 token/cookie 作为用户响应。"""
    app_cookie = "cookie-query-task10"
    refresh_token = "refresh-query-task10"
    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
            app_cookie=app_cookie,
            app_device_code="device-query-task10",
            app_refresh_token=refresh_token,
            app_status="",
        )

    service = AccountService(database, FakeAccountTransport(LoginResult.cancelled()), max_bind_count=2)
    response = await service.credentials(_actor())

    assert "1234567890123" in response.text
    assert "App 凭据：已保存" in response.text
    assert app_cookie not in response.text
    assert refresh_token not in response.text


@pytest.mark.asyncio
async def test_list_and_delete_all_remove_normalized_records(database):
    """查看和全量删除覆盖绑定、凭据两张归一化表。"""

    service = AccountService(
        database,
        FakeAccountTransport(LoginResult.cancelled()),
        max_bind_count=2,
    )
    await service.bind_uid(_actor(), "1234567890123")
    await service.bind_uid(_actor(), "2234567890123")
    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
            app_cookie="cookie-delete-all-fixture",
        )

    listing = await service.list_bindings(_actor())
    deleted = await service.delete_all(_actor())

    assert "1234567890123" in listing.text
    assert "2234567890123" in listing.text
    assert deleted.text == "已删除全部UID！"
    async with database.session() as session:
        assert (
            await AccountBindingRepository.list(
                session,
                user_id="user-1",
                bot_id="bot-1",
            )
            == []
        )
        assert (
            await CredentialRepository.list(
                session,
                user_id="user-1",
                bot_id="bot-1",
            )
            == []
        )


def test_login_input_is_typed_and_rejects_ambiguous_values():
    """命令解析只产生 typed attempt，不把任意输入直接交给 transport。"""
    assert parse_login_attempt("t" * 40).mode == "token"
    assert parse_login_attempt("13800138000,1234").mode == "sms"
    spaced_token = parse_login_attempt("t" * 20 + " " + "t" * 20)
    assert spaced_token.token == "t" * 40
    with pytest.raises(ValueError, match="登录参数"):
        parse_login_attempt("not-a-token")


@pytest.mark.asyncio
async def test_legacy_transport_maps_response_shape_errors_without_raw_detail():
    """legacy API 结构异常要归类为服务端错误，不把异常原文带出边界。"""
    class BrokenApi:
        async def login_app(self, _mobile, _code, _dev_code):
            raise TypeError("token=transport-shape-secret")

    from dnaby.utils.api.model import DNALoginRes

    transport = DnaApiAccountTransport()
    with pytest.raises(AccountTransportError) as raised:
        await transport._authenticate_sms(
            BrokenApi(),
            DNALoginRes,
            lambda _channel: "device-shape-fixture",
            LoginAttempt.from_sms("13800138000", "1234"),
        )

    error = raised.value
    assert error.kind is TransportErrorKind.SERVER
    assert "transport-shape-secret" not in str(error)
    assert "transport-shape-secret" not in repr(error)
