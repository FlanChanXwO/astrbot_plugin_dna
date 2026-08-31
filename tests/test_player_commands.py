"""Task 13 命令 registry 和 AstrBot Reply 边界测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.message_components import Reply

from src.entry.commands import CommandRequest, load_command_registry
from src.entry.event import EventActor, reply_id_from_event
from src.entry.response import PlainTextResponse
from src.modules.player.commands import (
    ROLE_DETAIL_PATTERN,
    player_role_detail_use_case,
)


def test_player_commands_are_explicit_and_legacy_patterns_are_preserved() -> None:
    registry = load_command_registry()
    specs = {spec.id: spec for spec in registry}

    assert {
        "role_info_card",
        "refresh_admin_role_card",
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "role_detail_card",
    } <= specs.keys()
    assert specs["role_info_card"].pattern == r"^kk(?:查询|卡片|角色|信息)$"
    assert specs["refresh_all_role_cards"].pattern == r"^kk刷新全部角色面板$"
    assert specs["clear_role_cache"].pattern.startswith(r"^kk清理(?P<char_name>")
    assert specs["clear_role_cache"].pattern.endswith(r"面板缓存$")
    assert specs["clear_player_cache"].pattern == r"^kk清理全部角色缓存$"
    assert specs["role_detail_card"].pattern == r"^kk" + ROLE_DETAIL_PATTERN[1:]
    assert registry.named_parameters("role_detail_card") == (
        "char_name",
        "weapon_name_1",
        "weapon_name_2",
    )


def test_reply_id_comes_from_public_astrbot_reply_component() -> None:
    event = SimpleNamespace(get_messages=lambda: [Reply(id="message-77")])

    assert reply_id_from_event(event) == "message-77"


def test_reply_id_ignores_non_reply_components() -> None:
    event = SimpleNamespace(get_messages=list)

    assert reply_id_from_event(event) is None


@pytest.mark.asyncio
async def test_role_detail_use_case_requires_player_service() -> None:
    request = CommandRequest(
        command_id="role_detail_card",
        text="角色甲面板",
        parameters={"char_name": "角色甲"},
        actor=EventActor("user-1", "bot-1"),
    )

    response = await player_role_detail_use_case(request, load_command_registry())

    assert isinstance(response, PlainTextResponse)
    assert response.text == "玩家查询服务不可用"
