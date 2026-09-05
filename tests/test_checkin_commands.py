"""签到命令的 registry 归属、正则和 handler 边界测试。"""

from __future__ import annotations

from collections.abc import Awaitable
from types import SimpleNamespace
from typing import cast

import pytest

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import PlainTextResponse, ResponseFactory
from src.modules.checkin import messages

CHECKIN_SPEC_IDS = {
    "sign",
    "sign_calendar",
    "sign_auto_enable",
    "sign_auto_disable",
    "sign_all",
    "sign_result_subscribe",
    "sign_group_report_subscribe",
}


def test_checkin_commands_are_registered_with_legacy_semantics() -> None:
    specs = {spec.id: spec for spec in load_command_registry()}

    assert CHECKIN_SPEC_IDS <= specs.keys()
    assert specs["sign"].pattern == r"^kk(?:签到|社区签到|每日任务|社区任务|库街区签到|sign)$"
    assert specs["sign"].permission == "user"
    assert specs["sign"].group == "签到服务"
    assert specs["sign_calendar"].pattern == r"^kk(?:签到日历|签到记录|签到历史)$"
    assert specs["sign_calendar"].permission == "user"
    assert specs["sign_auto_enable"].pattern == r"^kk开启自动签到$"
    assert specs["sign_auto_disable"].pattern == r"^kk关闭自动签到$"
    assert specs["sign_auto_enable"].permission == "user"
    assert specs["sign_auto_disable"].permission == "user"
    assert specs["sign_all"].pattern == r"^kk全部签到$"
    assert specs["sign_all"].permission == "admin"
    assert specs["sign_result_subscribe"].pattern == r"^kk(订阅|取消订阅)签到结果$"
    assert specs["sign_result_subscribe"].permission == "admin"


@pytest.mark.asyncio
async def test_sign_handler_reports_service_missing() -> None:
    """缺少 checkin_service 时 use case 必须返回显式不可用文案。"""

    spec = load_command_registry().get("sign")

    class Event:
        def get_message_str(self) -> str:
            return "kk签到"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

    result = await cast(Awaitable, spec.use_case(
        SimpleNamespace(
            command_id="sign",
            text="kk签到",
            parameters={},
            actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1"),
            services={},
        ),
        load_command_registry(),
    ))

    assert result == PlainTextResponse(messages.CHECKIN_SERVICE_UNAVAILABLE)


@pytest.mark.asyncio
async def test_generated_sign_all_handler_yields_aggregate_result() -> None:
    """真实生成 handler 必须把 admin 批量结果转换为 AstrBot 纯文本结果。"""

    class FakeCheckinService:
        async def manual_sign(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_calendar(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_all(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("全部签到执行完成\n今日成功签到 2 个账号，失败 0 个账号")

        async def subscribe_sign_result(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse(messages.SIGN_RESULT_SUBSCRIBED)

        async def set_auto_sign(
            self, _request: object, *, enabled: bool
        ) -> PlainTextResponse:
            return PlainTextResponse("自动签到状态已更新")

    class GeneratedSignPlugin:
        __module__ = "tests.generated_sign_plugin"

    class Event:
        def get_message_str(self) -> str:
            return "kk全部签到"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def plain_result(self, text: str) -> str:
            return text

    spec = load_command_registry().get("sign_all")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedSignPlugin, registry)
    plugin = GeneratedSignPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"checkin_service": FakeCheckinService()},
        ),
    )

    handler_name = "handle_sign_all"
    handler = getattr(plugin, handler_name)
    result = [item async for item in handler(Event())]

    assert "全部签到执行完成" in result[0]
    assert "今日成功签到 2 个账号，失败 0 个账号" in result[0]


@pytest.mark.asyncio
async def test_generated_group_report_handler_yields_subscription_result() -> None:
    """本群签到报告命令通过真实 handler 转换为纯文本结果。"""

    class FakeCheckinService:
        async def manual_sign(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_calendar(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_all(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def subscribe_sign_result(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def subscribe_group_report(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse(messages.SIGN_GROUP_REPORT_SUBSCRIBED)

        async def set_auto_sign(
            self, _request: object, *, enabled: bool
        ) -> PlainTextResponse:
            return PlainTextResponse("自动签到状态已更新")

    class GeneratedSignPlugin:
        __module__ = "tests.generated_sign_plugin"

    class Event:
        def get_message_str(self) -> str:
            return "kk订阅本群签到报告"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def plain_result(self, text: str) -> str:
            return text

    spec = load_command_registry().get("sign_group_report_subscribe")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedSignPlugin, registry)
    plugin = GeneratedSignPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"checkin_service": FakeCheckinService()},
        ),
    )

    result = [item async for item in plugin.handle_sign_group_report_subscribe(Event())]

    assert result == [messages.SIGN_GROUP_REPORT_SUBSCRIBED]


@pytest.mark.asyncio
async def test_generated_sign_result_handler_yields_subscription_result() -> None:
    """订阅命令通过真实 handler 转换为 AstrBot 纯文本结果。"""

    class FakeCheckinService:
        async def manual_sign(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_calendar(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def sign_all(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def subscribe_sign_result(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse(messages.SIGN_RESULT_SUBSCRIBED)

        async def set_auto_sign(
            self, _request: object, *, enabled: bool
        ) -> PlainTextResponse:
            return PlainTextResponse("自动签到状态已更新")

    class GeneratedSignPlugin:
        __module__ = "tests.generated_sign_plugin"

    class Event:
        def get_message_str(self) -> str:
            return "kk订阅签到结果"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def plain_result(self, text: str) -> str:
            return text

    spec = load_command_registry().get("sign_result_subscribe")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedSignPlugin, registry)
    plugin = GeneratedSignPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"checkin_service": FakeCheckinService()},
        ),
    )

    handler_name = "handle_sign_result_subscribe"
    handler = getattr(plugin, handler_name)
    result = [item async for item in handler(Event())]

    assert result == [messages.SIGN_RESULT_SUBSCRIBED]
