"""Goal 4 / Task 13：真实消息链中的命令文本归一化。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import At, AtAll, Image, Plain, Reply

from src.entry.commands import (
    CommandRegistry,
    CommandRequest,
    CommandSpec,
    install_command_handlers,
)
from src.entry.event import command_text_from_event
from src.entry.response import PlainTextResponse, ResponseFactory


def test_command_text_ignores_non_plain_components_before_and_after() -> None:
    event = SimpleNamespace(
        get_messages=lambda: [
            Reply(id="r1"),
            At(qq="target"),
            Plain(" kk卡片 "),
            Image(file="https://img.test/a.png"),
            AtAll(),
        ],
        get_message_str=lambda: "@target kk卡片 [图片] @全体成员",
    )
    assert command_text_from_event(event) == "kk卡片"


def test_command_text_combines_plain_fragments_and_falls_back_without_chain() -> None:
    event = SimpleNamespace(
        get_messages=lambda: [Plain("kk角色"), At(qq="target"), Plain("详情")],
        get_message_str=lambda: "fallback",
    )
    assert command_text_from_event(event) == "kk角色详情"
    assert (
        command_text_from_event(SimpleNamespace(get_message_str=lambda: " kk卡片 "))
        == "kk卡片"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "components",
    ([At(qq="target"), Plain("查角色")], [Plain("查角色"), At(qq="target")]),
)
async def test_generated_handler_matches_command_with_mention_on_either_side(
    components: list[object],
) -> None:
    seen: list[tuple[str, str | None]] = []

    async def use_case(
        request: CommandRequest, _registry: CommandRegistry, **_params: object
    ):
        seen.append((request.text, request.target_user_id))
        return PlainTextResponse("ok")

    spec = CommandSpec(
        id="mention_query",
        pattern=r"^查角色$",
        group="测试",
        name="查询",
        description="查询",
        examples=("查角色",),
        permission="user",
        use_case=use_case,
    )
    registry = CommandRegistry((spec,))

    class Plugin:
        __module__ = "tests.goal4_task13"
        _runtime = SimpleNamespace(commands=registry, services={}, responses=ResponseFactory())

    install_command_handlers(Plugin, registry)
    plugin = Plugin()
    event = SimpleNamespace(
        get_messages=lambda: components,
        get_message_str=lambda: "@target 查角色",
        get_sender_id=lambda: "actor",
        get_self_id=lambda: "bot",
        get_group_id=lambda: "group",
        unified_msg_origin="platform:group:g1",
        is_admin=lambda: False,
        plain_result=lambda text: text,
    )
    result = [item async for item in plugin.handle_mention_query(event)]
    assert result == ["ok"]
    assert seen == [("查角色", "target")]
