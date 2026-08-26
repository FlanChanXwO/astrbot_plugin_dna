"""密函/公告命令的 registry 归属、正则与 handler 边界测试。"""

from __future__ import annotations

from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import ImageResponse, PlainTextResponse, ResponseFactory
from src.modules.notices import messages

NOTICES_SPEC_IDS = {"mh", "mh_list", "ann", "mh_subscribe", "mh_subscribe_by_name", "mh_subscribe_cycle", "mh_pic_subscribe", "mh_text_subscribe", "mh_test", "ann_sub", "ann_unsub"}


def test_notices_commands_are_registered_with_legacy_semantics() -> None:
    specs = {spec.id: spec for spec in load_command_registry()}

    assert NOTICES_SPEC_IDS <= specs.keys()
    assert specs["mh"].pattern == r"^kk(?:密函|委托密函|mh)$"
    assert specs["mh"].permission == "user"
    assert specs["mh"].group == "密函"
    assert specs["mh_list"].pattern == r"^kk密函列表$"
    assert specs["mh_list"].permission == "user"
    assert specs["ann"].pattern == r"^kk公告(?:\s+(?P<index>\d+))?$"
    assert specs["ann"].permission == "user"
    assert specs["mh_subscribe_by_name"].permission == "user"
    assert specs["mh_subscribe_cycle"].permission == "user"
    assert specs["mh_pic_subscribe"].permission == "admin"
    assert specs["mh_text_subscribe"].permission == "admin"
    assert specs["mh_test"].permission == "owner"
    assert specs["ann_sub"].permission == "admin"
    assert specs["ann_unsub"].permission == "admin"


def test_ann_pattern_extracts_named_index() -> None:
    import re

    spec = load_command_registry().get("ann")
    match = re.match(spec.pattern, "kk公告 3")
    assert match is not None
    assert match.groupdict() == {"index": "3"}
    no_index = re.match(spec.pattern, "kk公告")
    assert no_index is not None
    assert no_index.groupdict() == {"index": None}


@pytest.mark.asyncio
async def test_notices_handler_reports_service_missing() -> None:
    """缺少 notices_service 时 use case 必须返回显式不可用文案。"""

    spec = load_command_registry().get("mh")

    result = await cast(Awaitable, spec.use_case(
        SimpleNamespace(
            command_id="mh",
            text="kk密函",
            parameters={},
            actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1", unified_msg_origin="group-1"),
            services={},
        ),
        load_command_registry(),
    ))

    assert result == PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)


@pytest.mark.asyncio
async def test_generated_ann_handler_yields_image_response() -> None:
    """真实生成 handler 把公告列表图片结果交给 AstrBot 边界。"""

    class FakeNoticesService:
        async def mh(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def mh_list(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def ann(self, _request: object) -> ImageResponse:
            return ImageResponse("rendered.png")

        async def subscribe_mh(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def unsubscribe_mh(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def mh_subscriptions(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def set_mh_push_time(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def toggle_mh_pic(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def toggle_mh_text(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def test_mh_push(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def subscribe_ann(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

        async def unsubscribe_ann(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("unused")

    class GeneratedNoticesPlugin:
        __module__ = "tests.generated_notices_plugin"

    class Event:
        def get_message_str(self) -> str:
            return "kk公告"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def get_messages(self) -> list:
            return []

        def plain_result(self, text: str) -> str:
            return text

        def image_result(self, image: object) -> object:
            return image

    spec = load_command_registry().get("ann")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedNoticesPlugin, registry)
    plugin = GeneratedNoticesPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"notices_service": FakeNoticesService()},
        ),
    )

    handler = cast(Any, plugin).handle_ann
    result = [item async for item in handler(Event())]

    assert result == ["rendered.png"]


@pytest.mark.asyncio
async def test_generated_mh_subscribe_handler_ats_user_in_group_chat() -> None:
    """群聊中执行密函订阅命令时返回带 At 的消息链。"""
    from astrbot.api.message_components import At, Plain

    class FakeNoticesService:
        async def mh(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def mh_list(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def ann(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def subscribe_mh(self, _request: object) -> PlainTextResponse:
            return PlainTextResponse("成功订阅密函【角色:拆解,武器:拆解,魔之楔:拆解】", need_at=True)
        async def unsubscribe_mh(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def mh_subscriptions(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def set_mh_push_time(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def toggle_mh_pic(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def toggle_mh_text(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def test_mh_push(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def subscribe_ann(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")
        async def unsubscribe_ann(self, _request: object) -> PlainTextResponse: return PlainTextResponse("")

    class GeneratedNoticesPlugin:
        __module__ = "tests.generated_notices_plugin"

    class GroupEvent:
        def get_message_str(self) -> str:
            return "kk订阅拆解密函"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def get_messages(self) -> list:
            return []

        def chain_result(self, components: object) -> object:
            return components

        def plain_result(self, text: str) -> str:
            return text

    class DirectEvent:
        def get_message_str(self) -> str:
            return "kk订阅拆解密函"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> None:
            return None

        def get_messages(self) -> list:
            return []

        def chain_result(self, components: object) -> object:
            return components

        def plain_result(self, text: str) -> str:
            return text

    spec = load_command_registry().get("mh_subscribe_by_name")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedNoticesPlugin, registry)
    plugin = GeneratedNoticesPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"notices_service": FakeNoticesService()},
        ),
    )

    handler = cast(Any, plugin).handle_mh_subscribe_by_name

    # 群聊测试：返回带 At 组件的消息链
    group_results = [item async for item in handler(GroupEvent())]
    assert len(group_results) == 1
    chain = group_results[0]
    assert len(chain) == 2
    assert isinstance(chain[0], At)
    assert chain[0].qq == "user-1"
    assert isinstance(chain[1], Plain)
    assert chain[1].text == "成功订阅密函【角色:拆解,武器:拆解,魔之楔:拆解】"

    # 私聊测试：直接返回纯文本
    direct_results = [item async for item in handler(DirectEvent())]
    assert direct_results == ["成功订阅密函【角色:拆解,武器:拆解,魔之楔:拆解】"]


@pytest.mark.asyncio
async def test_notices_service_adapts_prefix_for_forbidden_and_time_format():
    """当用户用特定前缀（如 dna）触发时，提示信息中的命令示例动态使用该前缀。"""
    from src.entry.commands import CommandRequest
    from src.modules.notices.service import NoticesService

    service = NoticesService(database=SimpleNamespace(), transport=SimpleNamespace(), privacy=SimpleNamespace(), renderer=SimpleNamespace(), subscriptions=SimpleNamespace())
    req_dna = CommandRequest(
        command_id="mh_subscribe_by_name",
        text="dna订阅全部密函",
        parameters={"mh_name": "全部"},
        actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1", unified_msg_origin="group-1"),
        matched_prefix="dna",
    )
    res = await service.subscribe_mh(req_dna)
    assert "[dna密函列表]" in res.text

    req_time = CommandRequest(
        command_id="mh_subscribe_cycle",
        text="dna订阅密函时间",
        parameters={"start": "invalid", "end": "invalid"},
        actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1", unified_msg_origin="group-1"),
        matched_prefix="dna",
    )
    res_time = await service.set_mh_push_time(req_time)
    assert "dna订阅密函时间17:23" in res_time.text
