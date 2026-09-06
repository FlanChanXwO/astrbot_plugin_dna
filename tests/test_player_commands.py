"""Task 13 命令 registry 和 AstrBot Reply 边界测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from astrbot.api.message_components import Reply

from src.entry.commands import CommandRequest, load_command_registry
from src.entry.event import EventActor, reply_id_from_event
from src.entry.response import PlainTextResponse
from src.modules.player.commands import (
    ROLE_DETAIL_PATTERN,
    player_clear_info_card_cache_use_case,
    player_refresh_info_card_use_case,
    player_role_detail_use_case,
)


def test_player_commands_are_explicit_and_legacy_patterns_are_preserved() -> None:
    registry = load_command_registry()
    specs = {spec.id: spec for spec in registry}

    assert {
        "role_info_card",
        "refresh_info_card_cache",
        "clear_info_card_cache",
        "refresh_admin_role_card",
        "refresh_role_card",
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "role_detail_card",
    } <= specs.keys()
    assert specs["role_info_card"].pattern == r"^kk(?:查询|卡片|角色|信息)$"
    assert specs["refresh_info_card_cache"].permission == "user"
    assert specs["refresh_info_card_cache"].group == "信息查询"
    assert specs["refresh_info_card_cache"].pattern == r"^kk刷新(?:基本信息)?卡片缓存$"
    assert specs["clear_info_card_cache"].permission == "user"
    assert specs["clear_info_card_cache"].group == "信息查询"
    assert specs["clear_info_card_cache"].pattern == r"^kk(?:清理|删除)(?:基本信息)?卡片缓存$"
    assert registry.match("kk刷新卡片缓存").command.id == "refresh_info_card_cache"
    assert registry.match("kk刷新基本信息卡片缓存").command.id == "refresh_info_card_cache"
    assert registry.match("kk清理卡片缓存").command.id == "clear_info_card_cache"
    assert registry.match("kk删除卡片缓存").command.id == "clear_info_card_cache"
    assert registry.match("kk删除基本信息卡片缓存").command.id == "clear_info_card_cache"
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


@pytest.mark.parametrize(
    "text",
    (
        "刷新菲娜面板",
        "刷新全部角色面板",
        "刷新123456的菲娜面板",
        "清理菲娜面板缓存",
    ),
)
def test_role_detail_pattern_reserves_management_prefixes(text: str) -> None:
    assert re.match(ROLE_DETAIL_PATTERN, text) is None


def test_role_info_help_examples_have_single_command_match() -> None:
    project_root = Path(__file__).resolve().parents[1]
    help_data = json.loads(
        (project_root / "src/resources/help/help.json").read_text(encoding="utf-8")
    )
    expected_command_ids = {
        "刷新角色面板": "refresh_role_card",
        "刷新全部角色面板": "refresh_all_role_cards",
        "清理角色面板缓存": "clear_role_cache",
        "清理角色缓存": "clear_player_cache",
        "角色详情卡片": "role_detail_card",
    }
    registry = load_command_registry()

    for item in help_data["角色信息"]["data"]:
        message = "kk" + item["eg"]
        matches = [
            spec.id for spec in registry if re.match(spec.pattern, message) is not None
        ]
        assert matches == [expected_command_ids[item["name"]]], message


def test_info_card_cache_help_examples_have_single_command_match() -> None:
    project_root = Path(__file__).resolve().parents[1]
    help_data = json.loads(
        (project_root / "src/resources/help/help.json").read_text(encoding="utf-8")
    )
    expected_command_ids = {
        "刷新基本信息卡片缓存": "refresh_info_card_cache",
        "清理基本信息卡片缓存": "clear_info_card_cache",
    }
    registry = load_command_registry()
    items = {item["name"]: item for item in help_data["信息查询"]["data"]}
    assert set(expected_command_ids) <= items.keys()

    for name in expected_command_ids:
        item = items[name]
        for example in item["eg"].split(" / "):
            message = "kk" + example
            matches = [
                spec.id
                for spec in registry
                if re.match(spec.pattern, message) is not None
            ]
            assert matches == [expected_command_ids[item["name"]]], message


def test_admin_refresh_has_single_command_match() -> None:
    registry = load_command_registry()
    message = "kk刷新123456的菲娜面板"
    matches = [
        spec.id for spec in registry if re.match(spec.pattern, message) is not None
    ]

    assert matches == ["refresh_admin_role_card"]


def test_reply_id_comes_from_public_astrbot_reply_component() -> None:
    event = SimpleNamespace(get_messages=lambda: [Reply(id="message-77")])

    assert reply_id_from_event(event) == "message-77"


def test_reply_id_ignores_non_reply_components() -> None:
    event = SimpleNamespace(get_messages=list)

    assert reply_id_from_event(event) is None


@pytest.mark.asyncio
async def test_info_card_cache_use_cases_delegate_to_their_dedicated_service_methods() -> None:
    calls: list[tuple[str, object]] = []

    class Service:
        async def refresh_info_card(self, request):
            calls.append(("refresh", request))
            return PlainTextResponse("刷新完成")

        async def clear_info_card_cache(self, request):
            calls.append(("clear", request))
            return PlainTextResponse("清理完成")

    services = {"player_service": Service()}
    refresh_request = CommandRequest(
        command_id="refresh_info_card_cache",
        text="刷新卡片缓存",
        parameters={},
        actor=EventActor("user-1", "bot-1"),
        services=services,
    )
    clear_request = CommandRequest(
        command_id="clear_info_card_cache",
        text="删除卡片缓存",
        parameters={},
        actor=EventActor("user-1", "bot-1"),
        services=services,
    )

    refresh_response = await player_refresh_info_card_use_case(
        refresh_request,
        load_command_registry(),
    )
    clear_response = await player_clear_info_card_cache_use_case(
        clear_request,
        load_command_registry(),
    )

    assert isinstance(refresh_response, PlainTextResponse)
    assert refresh_response.text == "刷新完成"
    assert isinstance(clear_response, PlainTextResponse)
    assert clear_response.text == "清理完成"
    assert [name for name, _request in calls] == ["refresh", "clear"]


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
