"""Task 14 资料命令 registry、权限和框架消息链边界。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import Image, Plain

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import (
    ChainResponse,
    ImageResponse,
    PlainTextResponse,
    ResponseFactory,
)


def test_encyclopedia_commands_are_explicit_and_legacy_patterns_are_preserved() -> None:
    specs = {spec.id: spec for spec in load_command_registry()}

    expected = {
        "stamina",
        "weekly_report_current",
        "weekly_report_last",
        "calendar",
        "dna_wiki",
        "dna_guide",
        "dna_code",
        "alias_list",
        "alias_all_list",
    }
    assert expected <= specs.keys()
    assert specs["stamina"].pattern == r"^(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$"
    assert specs["weekly_report_current"].pattern == r"^(?:本周周报|周报)$"
    assert specs["weekly_report_last"].pattern == r"^上周周报$"
    assert specs["calendar"].pattern == r"^日历$"
    assert specs["dna_code"].pattern == r"^(?:兑换码|cdk|CDK|code)$"
    assert specs["alias_list"].permission == "owner"
    assert specs["alias_all_list"].permission == "user"
    assert specs["dna_wiki"].pattern.startswith(r"^(?P<name>")
    assert specs["dna_guide"].pattern.startswith(r"^(?P<char_name>")


@pytest.mark.asyncio
async def test_response_factory_converts_framework_free_chain_parts() -> None:
    class Event:
        def chain_result(self, components: object) -> object:
            return components

        def plain_result(self, text: str) -> object:
            return text

        def image_result(self, image: object) -> object:
            return image

    result = ResponseFactory().build(
        Event(),
        ChainResponse((PlainTextResponse("作者"), ImageResponse("/tmp/guide.png"))),
    )

    assert isinstance(result, list)
    assert isinstance(result[0], Plain)
    assert result[0].text == "作者"
    assert isinstance(result[1], Image)
    assert result[1].file == "/tmp/guide.png"


@pytest.mark.asyncio
async def test_encyclopedia_use_case_reports_missing_service() -> None:
    registry = CommandRegistry(
        (spec for spec in load_command_registry() if spec.id == "calendar"),
    )

    class GeneratedPlugin:
        __module__ = "tests.generated_encyclopedia_plugin"

    install_command_handlers(GeneratedPlugin, registry)
    plugin = GeneratedPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(commands=registry, responses=ResponseFactory(), services={}),
    )

    class Event:
        def get_message_str(self) -> str:
            return "日历"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> None:
            return None

        def get_messages(self) -> list[object]:
            return []

        def plain_result(self, text: str) -> str:
            return text

    handler = plugin.handle_calendar
    result = [item async for item in handler(Event())]
    assert result == ["资料服务暂不可用，请检查插件配置"]
