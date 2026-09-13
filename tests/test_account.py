"""Task 10 账号 use case、transport 错误和敏感信息边界测试。"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from src.infrastructure.http.account import DnaApiAccountTransport
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.modules.account import messages
from src.modules.account.contracts import (
    AccountActor,
    AccountTransportError,
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
    TransportErrorKind,
)
from src.modules.account.service import AccountService, parse_login_attempt
from src.utils.constants.constants import DNA_GAME_ID


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

    def __init__(
        self, outcome: object, page_url: str = "https://login.test/session"
    ) -> None:
        self.outcome = outcome
        self.page_url = page_url
        self.attempts: list[LoginAttempt] = []
        self.actors: list[AccountActor] = []
        self.checked_credentials: list[LoginCredentials] = []

    async def authenticate_credentials(
        self,
        credentials: LoginCredentials,
    ) -> LoginResult:
        """记录并按构造结果验证已保存凭据，模拟实时上游校验。"""

        self.checked_credentials.append(credentials)
        if isinstance(self.outcome, AccountTransportError):
            raise self.outcome
        assert isinstance(self.outcome, LoginResult)
        return self.outcome

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
async def test_login_success_persists_roles_and_credentials_without_leaking_secrets(
    database,
):
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
            uid="1234567890123",
        )
        credential = await CredentialRepository.get(
            session,
            user_id="user-1",
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
        )
    assert [(binding.uid, binding.is_active) for binding in bindings] == [
        ("1234567890123", False),
        ("2234567890123", True),
    ]


@pytest.mark.asyncio
async def test_login_rolls_back_bindings_when_credential_write_fails(
    database, monkeypatch
):
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
        assert (
            await AccountBindingRepository.list(
                session,
                user_id="user-1",
            )
            == []
        )
        assert (
            await CredentialRepository.list(
                session,
                user_id="user-1",
            )
            == []
        )


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

    assert page_response.text == (
        "[二重螺旋] 您的id为【user-1】\n"
        "请复制地址到浏览器打开\n"
        " https://login.test/session\n"
        "登录地址10分钟内有效"
    )
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
    transport = FakeAccountTransport(
        AccountTransportError(kind, detail=secret_detail, status_code=502)
    )
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
                uid="1234567890123",
            )
            is None
        )


@pytest.mark.asyncio
async def test_get_credential_reveals_token_only_in_private_chat(database):
    """获取凭证：私聊返回真实凭证，群聊只返回提示且绝不泄露凭证。"""
    app_cookie = "cookie-secret-task10"
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie=app_cookie,
            app_device_code="device-query-task10",
            app_refresh_token="refresh-query-task10",
            app_status="",
        )

    service = AccountService(
        database, FakeAccountTransport(LoginResult.cancelled()), max_bind_count=2
    )

    private_response = await service.credentials(
        AccountActor(user_id="user-1", bot_id="bot-1", group_id=None)
    )
    assert "1234567890123" in private_response.text
    assert app_cookie in private_response.text

    group_response = await service.credentials(_actor())
    assert app_cookie not in group_response.text
    assert "私聊" in group_response.text


@pytest.mark.asyncio
async def test_check_credentials_reports_valid_state(database):
    """typed transport 实时校验成功时报告凭证有效，不修改任何状态。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-check",
            app_device_code="device-check",
            app_status="",
        )

    transport = FakeAccountTransport(
        LoginResult.success(
            LoginCredentials(
                channel=LoginChannel.APP,
                token="cookie-check",
                dev_code="device-check",
            )
        )
    )
    service = AccountService(database, transport, max_bind_count=2)
    response = await service.check_credentials(_actor())

    assert len(transport.checked_credentials) == 1
    assert transport.checked_credentials[0].token == "cookie-check"
    assert transport.checked_credentials[0].dev_code == "device-check"
    assert "有效" in response.text
    assert "失效" not in response.text
    assert "cookie-check" not in response.text
    async with database.session() as session:
        record = await CredentialRepository.get(
            session, user_id="user-1", uid="1234567890123"
        )
    assert record is not None
    assert record.app_status != "无效"


@pytest.mark.asyncio
async def test_check_credentials_restores_invalid_marker_after_successful_check(
    database,
):
    """曾被标记无效的凭证在实时验证成功后必须恢复，避免业务链路继续拒绝。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-check",
            app_device_code="device-check",
            app_status="无效",
        )

    transport = FakeAccountTransport(
        LoginResult.success(
            LoginCredentials(
                channel=LoginChannel.APP,
                token="cookie-check",
                dev_code="device-check",
            )
        )
    )
    service = AccountService(database, transport, max_bind_count=2)
    response = await service.check_credentials(_actor())

    assert "有效" in response.text
    async with database.session() as session:
        record = await CredentialRepository.get(
            session, user_id="user-1", uid="1234567890123"
        )
    assert record is not None
    assert record.app_status == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", [LoginResult.cancelled, LoginResult.failed])
async def test_check_credentials_never_reports_valid_for_non_success_results(
    database, factory
):
    """cancelled / failed 只是本次校验未完成，不得报告「凭证有效」。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-check",
            app_device_code="device-check",
            app_status="",
        )

    transport = FakeAccountTransport(factory())
    service = AccountService(database, transport, max_bind_count=2)
    response = await service.check_credentials(_actor())

    assert "暂时无法验证" in response.text
    assert "有效" not in response.text


@pytest.mark.asyncio
async def test_check_credentials_persists_invalid_only_when_upstream_confirms(database):
    """只有上游明确判定凭据失效才写回无效状态并要求重新登录。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-check",
            app_device_code="device-check",
            app_status="",
        )

    transport = FakeAccountTransport(
        AccountTransportError(TransportErrorKind.CREDENTIAL, detail="upstream invalid")
    )
    service = AccountService(database, transport, max_bind_count=2)
    response = await service.check_credentials(_actor())

    assert "失效" in response.text
    assert "dna登录" in response.text
    async with database.session() as session:
        record = await CredentialRepository.get(
            session, user_id="user-1", uid="1234567890123"
        )
    assert record is not None
    assert record.app_status == "无效"


@pytest.mark.asyncio
async def test_check_credentials_stale_invalid_writeback_never_overwrites_relogin(
    database,
):
    """检查期间用户重新登录后，旧 token 的失效结论不得污染新凭据。"""

    class ReloginThenCredentialError(FakeAccountTransport):
        """校验期间模拟并发重新登录，再返回上游凭据失效。"""

        async def authenticate_credentials(
            self,
            credentials: LoginCredentials,
        ) -> LoginResult:
            # 记录本次校验的凭据后，模拟并发重新登录，再返回旧凭据失效。
            self.checked_credentials.append(credentials)
            async with service.database.transaction() as session:
                await CredentialRepository.save_app(
                    session,
                    user_id="user-1",
                    uid="1234567890123",
                    token="cookie-new",
                    device_code="device-new",
                )
            raise AccountTransportError(
                TransportErrorKind.CREDENTIAL,
                detail="upstream invalid for old token",
            )

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-old",
            app_device_code="device-old",
            app_status="",
        )

    service = AccountService(
        database, ReloginThenCredentialError(None), max_bind_count=2
    )
    response = await service.check_credentials(_actor())

    # 旧凭据确实失效，但数据库已是新凭据：不得报告失效，也不得覆盖新凭据状态。
    assert "暂时无法验证" in response.text
    async with database.session() as session:
        record = await CredentialRepository.get(
            session, user_id="user-1", uid="1234567890123"
        )
    assert record is not None
    assert record.app_cookie == "cookie-new"
    assert record.app_device_code == "device-new"
    assert record.app_status != "无效"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [TransportErrorKind.NETWORK, TransportErrorKind.STATUS, TransportErrorKind.SERVER],
)
async def test_check_credentials_reports_indeterminate_for_non_credential_failures(
    database, kind
):
    """网络/状态码/服务端失败均不得判定为凭据失效，也不修改任何持久化状态。"""
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="1234567890123",
            app_cookie="cookie-check",
            app_device_code="device-check",
            app_status="",
        )

    transport = FakeAccountTransport(AccountTransportError(kind, detail="not credential"))
    service = AccountService(database, transport, max_bind_count=2)
    response = await service.check_credentials(_actor())

    assert "暂时无法验证" in response.text
    assert "失效" not in response.text
    assert "重新登录" not in response.text
    async with database.session() as session:
        record = await CredentialRepository.get(
            session, user_id="user-1", uid="1234567890123"
        )
    assert record is not None
    assert record.app_status != "无效"


@pytest.mark.asyncio
async def test_check_credentials_requires_complete_app_credentials(database):
    """空 token 的残缺记录（只有设备码/refresh_token）不可用于校验。"""
    for cookie in ("", "  "):
        async with database.transaction() as session:
            # save_app 是 upsert，覆盖上一轮残留的同 UID 记录。
            await CredentialRepository.save_app(
                session,
                user_id="user-1",
                uid="1234567890123",
                token=cookie,
                device_code="device-only",
                refresh_token="refresh-only",
            )

        service = AccountService(database, FakeAccountTransport(None), max_bind_count=2)
        response = await service.check_credentials(_actor())
        assert response.text == messages.NOT_LOGGED_IN


@pytest.mark.asyncio
async def test_get_credential_skips_records_without_token(database):
    """只有设备码/refresh_token 的记录不输出空凭证；无可返回凭证时空回复。"""
    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            uid="123456789010",
            app_cookie="",
            app_device_code="device-only",
            app_refresh_token="refresh-only",
        )

    service = AccountService(database, FakeAccountTransport(None), max_bind_count=2)

    private = AccountActor(user_id="user-1", bot_id="bot-1", group_id=None)
    response = await service.credentials(private)
    assert response.text == messages.CREDENTIALS_EMPTY


@pytest.mark.asyncio
async def test_real_transport_boundary_classifies_credential_and_network_failures(
    monkeypatch,
):
    """真实 DnaApiAccountTransport 边界：实时角色列表校验 + 四类错误分类。"""
    from src.infrastructure.http.account import DnaApiAccountTransport

    # src.utils 导出的 dna_api 就是 DNAApi 单例实例，transport 内部同样按属性访问。
    from src.utils import dna_api
    from src.utils.api.request_util import DNAApiResp

    transport = DnaApiAccountTransport()
    credentials = LoginCredentials(
        channel=LoginChannel.APP,
        token="token-real",
        dev_code="device-real",
    )
    calls: list[tuple[str, str]] = []

    async def fake_get_app_role_list(token: str, dev_code: str):
        calls.append((token, dev_code))
        return outcomes.pop(0)

    def login_log_probe(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("凭证检查不得走 login_log 缓存路径")

    outcomes = [
        DNAApiResp.ok(
            {
                "roles": [
                    {
                        "gameId": DNA_GAME_ID,
                        "gameName": "二重螺旋",
                        "showVoList": [
                            {
                                "roleId": "1234567890123",
                                "roleBoundId": "bound-1",
                                "roleName": "角色甲",
                                "isDefault": 1,
                                "headUrl": "https://avatar.test/1.png",
                                "level": 42,
                                "roleRegisterTime": "2026-01-01 00:00:00",
                                "boundType": 0,
                            }
                        ],
                    }
                ]
            }
        ),
        DNAApiResp.err("token已失效", code=200),
        DNAApiResp.err("服务暂时不可用", code=500),
    ]
    monkeypatch.setattr(dna_api, "get_app_role_list", fake_get_app_role_list)
    monkeypatch.setattr(dna_api, "login_log", login_log_probe)

    valid = await transport.authenticate_credentials(credentials)
    assert valid.roles and valid.roles[0].uid == "1234567890123"

    with pytest.raises(AccountTransportError) as credential_error:
        await transport.authenticate_credentials(credentials)
    assert credential_error.value.kind is TransportErrorKind.CREDENTIAL

    with pytest.raises(AccountTransportError) as status_error:
        await transport.authenticate_credentials(credentials)
    # 5xx 业务失败按既有边界归类为 STATUS，不属于凭据失效。
    assert status_error.value.kind is TransportErrorKind.STATUS

    async def network_failure(token: str, dev_code: str):
        raise OSError("network unreachable")

    monkeypatch.setattr(dna_api, "get_app_role_list", network_failure)
    with pytest.raises(AccountTransportError) as network_error:
        await transport.authenticate_credentials(credentials)
    assert network_error.value.kind is TransportErrorKind.NETWORK

    # 每次校验都实时调用角色列表接口，且从未触达 login_log 缓存路径。
    assert len(calls) == 3

    async def programming_bug(token: str, dev_code: str):
        raise RuntimeError("unexpected bug in caller code")

    monkeypatch.setattr(dna_api, "get_app_role_list", programming_bug)
    # 编程缺陷不属于 transport 失败分类，必须原样向上抛出，
    # 不得被包装成 SERVER /「暂时无法验证」掩盖。
    with pytest.raises(RuntimeError):
        await transport.authenticate_credentials(credentials)


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
            )
            == []
        )
        assert (
            await CredentialRepository.list(
                session,
                user_id="user-1",
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

    from src.utils.api.model import DNALoginRes

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


@pytest.mark.asyncio
async def test_legacy_transport_maps_unexpected_api_errors_without_raw_detail():
    """第三方 API 未预期异常也必须变成安全的服务端错误。"""

    class BrokenApi:
        async def login_app(self, _mobile, _code, _dev_code):
            raise RuntimeError("token=unexpected-api-secret")

    from src.utils.api.model import DNALoginRes

    transport = DnaApiAccountTransport()
    with pytest.raises(AccountTransportError) as raised:
        await transport._authenticate_sms(
            BrokenApi(),
            DNALoginRes,
            lambda _channel: "device-unexpected-fixture",
            LoginAttempt.from_sms("13800138000", "1234"),
        )

    error = raised.value
    assert error.kind is TransportErrorKind.SERVER
    assert "unexpected-api-secret" not in str(error)
    assert "unexpected-api-secret" not in repr(error)
