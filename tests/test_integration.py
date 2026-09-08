"""插件关键全链路与恢复边界测试。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from src.bootstrap import build_runtime
from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
    load_command_registry,
)
from src.entry.event import EventActor
from src.entry.response import PlainTextResponse, ResponseFactory
from src.infrastructure.config.settings import LoginSettings
from src.infrastructure.persistence import AsyncDatabase, CredentialRecord
from src.modules.account import login_flow as login_flow_module
from src.modules.account import messages
from src.modules.account.contracts import LoginChannel, LoginCredentials
from src.modules.account.login_flow import LoginFlowCoordinator
from src.modules.account.transport import (
    SseTransport,
    TransportError,
    TransportResult,
    build_transport,
)


class _Context:
    """只实现 runtime 组装和生命周期测试需要的宿主接口。"""

    def register_web_api(self, *args: object) -> None:
        return None


class _Event:
    """提供动态登录 handler 所需的 AstrBot 公开事件方法。"""

    unified_msg_origin = "test:private:user-1"

    def __init__(self, message: str) -> None:
        self.message = message

    def get_message_str(self) -> str:
        return self.message

    def get_sender_id(self) -> str:
        return "user-1"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> None:
        return None

    def plain_result(self, text: str) -> str:
        return text


@pytest.mark.asyncio
async def test_default_runtime_login_handler_returns_live_local_url(tmp_path) -> None:
    """默认 local runtime 的 kk登录 必须立即返回可打开的登录链接。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    runtime = build_runtime(
        _Context(),
        {"login": {"transport": "local", "port": 0}},
        database=database,
    )

    class GeneratedLoginPlugin:
        __module__ = "tests.generated_fullchain_recovery_plugin"

    try:
        await runtime.initialize()
        install_command_handlers(GeneratedLoginPlugin, load_command_registry())
        plugin = GeneratedLoginPlugin()
        object.__setattr__(plugin, "_runtime", runtime)

        result = [item async for item in plugin.handle_account_login(_Event("kk登录"))]

        assert len(result) == 1
        assert result[0].startswith("登录地址：http://localhost:")
        assert "/astrbot_plugin_dnaby/dna/i/" in result[0]
    finally:
        await runtime.terminate()


@pytest.mark.asyncio
async def test_local_login_flow_serves_app_routes_and_cleans_completed_session() -> (
    None
):
    """本地登录页的 App 短信、提交和通知链路使用同一会话。"""

    class AccountTransport:
        async def request_sms_code(
            self,
            _mobile: str,
            _validation: str,
            _dev_code: str,
        ) -> None:
            return None

    class AccountService:
        def __init__(self) -> None:
            self.attempts: list[object] = []

        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("local App 登录不应走外置凭据回执")

        async def login(self, _actor: EventActor, attempt: object) -> PlainTextResponse:
            self.attempts.append(attempt)
            return PlainTextResponse("登录成功")

    notified: list[str] = []

    async def notify(_actor: EventActor, response: PlainTextResponse) -> None:
        notified.append(response.text)

    account_service = AccountService()
    flow = LoginFlowCoordinator(
        account_service,
        LoginSettings(transport="local", port=0),
        account_transport=AccountTransport(),
        notify=notify,
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        login_response = await flow.begin(actor)
        login_url = login_response.text.removeprefix("登录地址：")
        auth = next(iter(flow._sessions.values())).auth

        async with aiohttp.ClientSession() as client:
            async with client.get(login_url) as response:
                assert response.status == 200
                page = await response.text()
            assert "Web 登录" not in page

            async with client.post(
                f"{flow.local_server.base_url}/dna/getSmsCode",
                json={
                    "auth": auth,
                    "mobile": "13800138000",
                    "vJson": "validated",
                },
            ) as response:
                assert response.status == 200
                assert (await response.json())["success"] is True

            async with client.post(
                f"{flow.local_server.base_url}/dna/login",
                json={
                    "auth": auth,
                    "mobile": "13800138000",
                    "code": "1234",
                },
            ) as response:
                assert response.status == 200
                assert (await response.json())["success"] is True

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(account_service.attempts) == 1
        assert notified == ["登录成功"]
        assert flow.active_session_count == 0
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_dynamic_handler_logs_unexpected_exception_and_returns_stable_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """未预期异常必须进入 AstrBot 日志，用户只能看到稳定提示。"""

    async def failing_use_case(
        _request: CommandRequest,
        _registry: CommandRegistry,
        **_parameters: object,
    ) -> PlainTextResponse:
        raise RuntimeError("upstream response body must stay private")

    class GeneratedUnexpectedErrorPlugin:
        __module__ = "tests.generated_unexpected_error_plugin"

    registry = CommandRegistry(
        (
            CommandSpec(
                id="unexpected_error",
                pattern=r"^异常$",
                group="测试",
                name="异常",
                description="测试异常边界",
                examples=("异常",),
                permission="user",
                use_case=failing_use_case,
            ),
        ),
    )
    install_command_handlers(GeneratedUnexpectedErrorPlugin, registry)

    class Event:
        def get_message_str(self) -> str:
            return "异常"

        def plain_result(self, text: str) -> tuple[str, str]:
            return ("plain", text)

    plugin = GeneratedUnexpectedErrorPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(commands=registry, responses=ResponseFactory(), services={}),
    )

    with caplog.at_level(logging.ERROR, logger="astrbot"):
        result = [item async for item in plugin.handle_unexpected_error(Event())]

    assert result == [("plain", "命令执行失败，请稍后重试；管理员可查看日志了解详情。")]
    assert "unexpected_error" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "upstream response body must stay private" not in caplog.text


@pytest.mark.asyncio
async def test_login_flow_unexpected_exception_does_not_log_sensitive_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """登录等待异常只记录分类，不把外置服务正文写入日志。"""

    class ExternalTransport:
        async def start(self, **kwargs: object) -> str:
            return f"https://login.example.test/dna/i/{kwargs['auth']}"

        async def listen(self, _auth: str) -> TransportResult:
            raise RuntimeError("upstream login body contains secret-token")

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("认证不应在监听异常后执行")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("认证不应在监听异常后执行")

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=object(),
        external_transport=ExternalTransport(),
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    with caplog.at_level(logging.ERROR, logger="astrbot"):
        await flow.start()
        try:
            await flow.begin(actor)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        finally:
            await flow.stop()

    assert "登录流程等待出现未预期异常" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "upstream login body contains secret-token" not in caplog.text


@pytest.mark.asyncio
async def test_login_flow_start_unexpected_exception_returns_stable_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """外置服务启动异常也必须被转换为稳定提示。"""

    class ExternalTransport:
        async def start(self, **_kwargs: object) -> str:
            raise RuntimeError("start response contains start-secret")

        async def listen(self, _auth: str) -> TransportResult:
            raise AssertionError("启动失败后不应创建监听任务")

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("启动失败后不应认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("启动失败后不应认证")

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=object(),
        external_transport=ExternalTransport(),
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    with caplog.at_level(logging.ERROR, logger="astrbot"):
        await flow.start()
        try:
            response = await flow.begin(actor)
        finally:
            await flow.stop()

    assert response.text == messages.LOGIN_SERVICE_FAILED
    assert flow.active_session_count == 0
    assert "登录流程启动出现未预期异常" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "start response contains start-secret" not in caplog.text


@pytest.mark.asyncio
async def test_login_flow_sms_unexpected_exception_returns_stable_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """短信适配器的未预期异常不得变成含服务端正文的 500。"""

    class ExternalTransport:
        async def start(self, **kwargs: object) -> str:
            return f"https://login.example.test/dna/i/{kwargs['auth']}"

        async def listen(self, _auth: str) -> TransportResult:
            await asyncio.Event().wait()
            raise AssertionError("监听任务应由测试清理")

    class AccountTransport:
        async def request_sms_code(
            self,
            _mobile: str,
            _validation: str,
            _dev_code: str,
        ) -> bool:
            raise RuntimeError("sms response contains sms-secret")

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("短信请求失败后不应认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("短信请求失败后不应认证")

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=AccountTransport(),
        external_transport=ExternalTransport(),
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        await flow.begin(actor)
        auth = next(iter(flow._sessions.values())).auth

        async def json(*, default: object = None) -> dict[str, str]:
            return {
                "auth": auth,
                "mobile": "13800138000",
                "vJson": "validated",
            }

        monkeypatch.setattr(
            login_flow_module,
            "request",
            SimpleNamespace(json=json),
        )
        with caplog.at_level(logging.ERROR, logger="astrbot"):
            result = await flow._get_sms_code()
    finally:
        await flow.stop()

    assert result == {"success": False, "msg": messages.LOGIN_SERVICE_FAILED}
    assert "登录流程请求短信出现未预期异常" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "sms response contains sms-secret" not in caplog.text


def test_credential_model_is_app_only() -> None:
    """凭据 ORM 在迁移后只能暴露 App 字段。"""

    assert set(CredentialRecord.__table__.columns.keys()) == {
        "id",
        "user_id",
        "uid",
        "app_cookie",
        "app_device_code",
        "app_d_num",
        "app_refresh_token",
        "app_status",
    }


def test_transport_result_repr_redacts_credentials_and_service_message() -> None:
    """外置回执 DTO 被意外记录时也不得暴露敏感字段。"""

    result = TransportResult(
        status="success",
        msg="server response contains service-secret",
        token="app-result-token",
        dev_code="app-result-device",
        d_num="app-result-dnum",
        refresh_token="app-result-refresh",
    )

    rendered = repr(result)
    assert "app-result-token" not in rendered
    assert "app-result-device" not in rendered
    assert "app-result-dnum" not in rendered
    assert "app-result-refresh" not in rendered
    assert "service-secret" not in rendered


def test_credential_migration_drops_web_columns_and_preserves_app_data(
    tmp_path: Path,
) -> None:
    """0004 必须物理删除五个 Web 列，同时保留身份与 App 数据。"""

    try:
        from alembic.config import Config
    except ModuleNotFoundError:
        pytest.skip("alembic dependency is unavailable in this test runtime")

    from alembic import command

    database_path = tmp_path / "migration.sqlite3"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    command.upgrade(config, "0003_global_identity")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO account_bindings (user_id, group_id, uid, is_active)
            VALUES (?, ?, ?, ?)
            """,
            ("user-1", "group-1", "1234567890123", 1),
        )
        connection.execute(
            """
            INSERT INTO credential_records (
                user_id, uid, app_cookie, app_device_code, app_d_num,
                app_refresh_token, app_status, web_token, web_device_code,
                web_d_num, web_refresh_token, web_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "1234567890123",
                "app-cookie",
                "app-device",
                "app-dnum",
                "app-refresh",
                "valid",
                "web-token",
                "web-device",
                "web-dnum",
                "web-refresh",
                "valid",
            ),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(credential_records)")
        }
        app_record = connection.execute(
            """
            SELECT user_id, uid, app_cookie, app_device_code, app_d_num,
                   app_refresh_token, app_status
            FROM credential_records
            """,
        ).fetchone()

    assert columns == {
        "id",
        "user_id",
        "uid",
        "app_cookie",
        "app_device_code",
        "app_d_num",
        "app_refresh_token",
        "app_status",
    }
    assert app_record == (
        "user-1",
        "1234567890123",
        "app-cookie",
        "app-device",
        "app-dnum",
        "app-refresh",
        "valid",
    )


@pytest.mark.parametrize("transport_name", ["http_poll", "sse", "ws"])
def test_external_login_transports_use_typed_shared_secret(transport_name: str) -> None:
    """三种外置 transport 都必须由显式 typed 配置构造。"""

    transport = build_transport(
        "https://login.example.test/",
        transport_name,
        "typed-shared-secret",
    )

    assert transport.base_url == "https://login.example.test"
    assert transport.shared_secret == "typed-shared-secret"


@pytest.mark.asyncio
async def test_external_login_flow_notifies_and_cleans_completed_session() -> None:
    """外置回执应回到账号服务，并在完成后清理等待会话。"""

    class ExternalTransport:
        def __init__(self) -> None:
            self.started: list[str] = []

        async def start(self, **kwargs: object) -> str:
            auth = str(kwargs["auth"])
            self.started.append(auth)
            return f"https://login.example.test/dna/i/{auth}"

        async def listen(self, auth: str) -> TransportResult:
            assert auth in self.started
            return TransportResult(
                status="success",
                channel=LoginChannel.APP,
                token="app-token",
                dev_code="app-device",
            )

    class AccountService:
        def __init__(self) -> None:
            self.credentials: list[LoginCredentials] = []

        async def login_with_credentials(
            self,
            _actor: EventActor,
            credentials: LoginCredentials,
        ) -> PlainTextResponse:
            self.credentials.append(credentials)
            return PlainTextResponse("登录成功")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            return PlainTextResponse("登录成功")

    notified: list[str] = []

    async def notify(_actor: EventActor, response: PlainTextResponse) -> None:
        notified.append(response.text)

    account_service = AccountService()
    flow = LoginFlowCoordinator(
        account_service,
        LoginSettings(
            transport="http_poll",
            url="https://public.example.test",
            shared_secret="typed-shared-secret",
        ),
        account_transport=object(),
        external_transport=ExternalTransport(),
        notify=notify,
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        response = await flow.begin(actor)
        assert response.text.startswith("登录地址：https://login.example.test/dna/i/")
        assert flow.active_session_count == 1
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert account_service.credentials[0].token == "app-token"
        assert notified == ["登录成功"]
        assert flow.active_session_count == 0
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_external_login_flow_rejects_unsupported_channel_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """旧外置服务直接返回 Web channel 时也必须稳定失败。"""

    class ExternalTransport:
        async def start(self, **kwargs: object) -> str:
            return f"https://login.example.test/dna/i/{kwargs['auth']}"

        async def listen(self, _auth: str) -> TransportResult:
            return TransportResult(status="success", channel="web")  # type: ignore[arg-type]

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("不支持的渠道不得进入凭据认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("不支持的渠道不得进入短信认证")

    notified: list[str] = []

    async def notify(_actor: EventActor, response: PlainTextResponse) -> None:
        notified.append(response.text)

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=object(),
        external_transport=ExternalTransport(),
        notify=notify,
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    with caplog.at_level(logging.WARNING, logger="astrbot"):
        await flow.start()
        try:
            await flow.begin(actor)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        finally:
            await flow.stop()

    assert notified == [messages.LOGIN_SERVICE_FAILED]
    assert "登录流程收到不支持的渠道" in caplog.text
    assert "web" not in caplog.text


@pytest.mark.asyncio
async def test_external_login_flow_deduplicates_concurrent_begin_requests() -> None:
    """同一消息作用域的并发登录请求只能启动一个外置会话。"""

    class ExternalTransport:
        def __init__(self) -> None:
            self.start_count = 0
            self.listen_started = asyncio.Event()
            self.release_listen = asyncio.Event()

        async def start(self, **kwargs: object) -> str:
            self.start_count += 1
            await asyncio.sleep(0)
            return f"https://login.example.test/dna/i/{kwargs['auth']}"

        async def listen(self, _auth: str) -> TransportResult:
            self.listen_started.set()
            await self.release_listen.wait()
            return TransportResult(status="cancelled")

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("取消回执不得进入凭据认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("取消回执不得进入短信认证")

    external = ExternalTransport()
    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=object(),
        external_transport=external,
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        responses = await asyncio.gather(flow.begin(actor), flow.begin(actor))
        assert external.start_count == 1
        assert responses[0].text == responses[1].text
        assert flow.active_session_count == 1
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_login_flow_does_not_remove_replacement_session_during_cleanup() -> None:
    """旧会话完成时不得误删同一作用域刚替换的新会话。"""

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("local 测试不应走外置凭据认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("测试不应走短信认证")

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="local", port=0),
        account_transport=object(),
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        await flow.begin(actor)
        first_session = next(iter(flow._sessions.values()))
        first_session.response = PlainTextResponse("旧会话")
        first_session.completed.set()

        await flow.begin(actor)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert flow.active_session_count == 1
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_external_login_cancelled_result_notifies_cancelled_and_cleans_session() -> (
    None
):
    """外置服务明确返回 cancelled 时应保留取消语义并清理会话。"""

    class ExternalTransport:
        async def start(self, **kwargs: object) -> str:
            return f"https://login.example.test/dna/i/{kwargs['auth']}"

        async def listen(self, _auth: str) -> TransportResult:
            return TransportResult(status="cancelled")

    class AccountService:
        async def login_with_credentials(
            self,
            _actor: EventActor,
            _credentials: LoginCredentials,
        ) -> PlainTextResponse:
            raise AssertionError("取消回执不得进入凭据认证")

        async def login(
            self, _actor: EventActor, _attempt: object
        ) -> PlainTextResponse:
            raise AssertionError("取消回执不得进入短信认证")

    notified: list[str] = []

    async def notify(_actor: EventActor, response: PlainTextResponse) -> None:
        notified.append(response.text)

    flow = LoginFlowCoordinator(
        AccountService(),
        LoginSettings(transport="http_poll", url="https://public.example.test"),
        account_transport=object(),
        external_transport=ExternalTransport(),
        notify=notify,
    )
    actor = EventActor(
        user_id="user-1",
        bot_id="bot-1",
        unified_msg_origin="private:user-1",
    )

    await flow.start()
    try:
        response = await flow.begin(actor)
        assert response.text.startswith("登录地址：")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert notified == ["登录已取消"]
        assert flow.active_session_count == 0
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_external_login_payload_parse_error_is_safe() -> None:
    """外置服务返回畸形凭据时不得把服务端正文带进异常。"""

    class Response:
        async def aiter_lines(self):
            yield 'data: {"status":"success","credential":{"token":"secret-response-token"}}'
            yield ""

    with pytest.raises(TransportError) as error:
        await SseTransport._consume_sse(Response())

    assert "secret-response-token" not in str(error.value)


def test_repository_has_no_goal_workspaces() -> None:
    """阶段性 goal 工作区不得重新进入长期仓库结构。"""

    project_root = Path(__file__).resolve().parents[1]
    populated_goal_dirs = [
        path.name
        for path in project_root.glob("goal-*")
        if path.is_dir() and any(path.iterdir())
    ]
    assert populated_goal_dirs == []
