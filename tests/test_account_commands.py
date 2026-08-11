"""账号命令到 typed actor/service 边界的 AstrBot 事件 fixture 测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bootstrap import build_runtime
from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import PlainTextResponse, ResponseFactory
from src.modules.account.contracts import AccountActor


class FakeAccountService:
    """只观察命令层是否传递正确作用域和 named 参数。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, AccountActor, str | None]] = []

    async def begin_login(self, actor: AccountActor) -> PlainTextResponse:
        self.calls.append(("begin_login", actor, None))
        return PlainTextResponse("登录页已启动")

    async def bind_uid(self, actor: AccountActor, uid: str) -> PlainTextResponse:
        self.calls.append(("bind_uid", actor, uid))
        return PlainTextResponse("绑定成功")


class Event:
    """实现 AstrBot 公开 actor 方法和纯文本响应方法。"""

    def __init__(self, message: str, *, with_actor: bool = True) -> None:
        self.message = message
        self.with_actor = with_actor

    def get_message_str(self) -> str:
        return self.message

    def get_sender_id(self) -> str | None:
        return "user-1" if self.with_actor else None

    def get_self_id(self) -> str | None:
        return "bot-1" if self.with_actor else None

    def get_group_id(self) -> str:
        return "group-1"

    def plain_result(self, text: str) -> str:
        return text


@pytest.mark.asyncio
async def test_account_handler_extracts_actor_and_named_uid() -> None:
    """命令 handler 只从公开 event 方法提取 actor，并隔离自己的正则参数。"""

    class GeneratedAccountPlugin:
        __module__ = "tests.generated_account_plugin"

    registry = load_command_registry()
    install_command_handlers(GeneratedAccountPlugin, registry)
    service = FakeAccountService()
    plugin = GeneratedAccountPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"account_service": service},
        ),
    )

    handler_name = "handle_account_bind"
    handler = getattr(plugin, handler_name)
    result = [item async for item in handler(Event("绑定1234567890123"))]

    assert result == ["绑定成功"]
    assert service.calls == [
        (
            "bind_uid",
            AccountActor("user-1", "bot-1", "group-1"),
            "1234567890123",
        )
    ]


@pytest.mark.asyncio
async def test_account_handler_requires_event_actor() -> None:
    """没有可定位作用域时显式返回错误，不把账号操作落到默认用户。"""

    class GeneratedMissingActorPlugin:
        __module__ = "tests.generated_missing_actor_plugin"

    registry = CommandRegistry(
        (registry_spec for registry_spec in load_command_registry()
         if registry_spec.id == "account_bind"),
    )
    install_command_handlers(GeneratedMissingActorPlugin, registry)
    plugin = GeneratedMissingActorPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"account_service": FakeAccountService()},
        ),
    )

    handler_name = "handle_account_bind"
    handler = getattr(plugin, handler_name)
    result = [
        item async for item in handler(Event("绑定1234567890123", with_actor=False))
    ]

    assert result == ["无法识别当前用户，暂不能执行账号操作！"]


@pytest.mark.asyncio
async def test_account_login_without_argument_starts_page_transport() -> None:
    """无参数登录直接调用 begin_login，不把空文本送入认证 transport。"""

    class GeneratedLoginPlugin:
        __module__ = "tests.generated_login_plugin"

    registry = CommandRegistry(
        (registry_spec for registry_spec in load_command_registry()
         if registry_spec.id == "account_login"),
    )
    install_command_handlers(GeneratedLoginPlugin, registry)
    service = FakeAccountService()
    plugin = GeneratedLoginPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"account_service": service},
        ),
    )

    handler_name = "handle_account_login"
    handler = getattr(plugin, handler_name)
    result = [item async for item in handler(Event("dna登录"))]

    assert result == ["登录页已启动"]
    assert service.calls[0][0] == "begin_login"


@pytest.mark.asyncio
async def test_bootstrap_exposes_injected_account_service() -> None:
    """bootstrap 只组装 service，不把账号依赖藏进全局 registry。"""

    class Context:
        def register_web_api(self, *args: object) -> None:
            return None

    service = FakeAccountService()
    runtime = build_runtime(
        Context(),
        {},
        services={"account_service": service},
    )

    assert runtime.services["account_service"] is service
    await runtime.initialize()
    await runtime.terminate()
