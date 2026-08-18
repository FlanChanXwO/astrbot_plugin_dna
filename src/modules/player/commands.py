"""玩家查询命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import PlayerCommandRequest
from .service import PlayerService

PATTERN = r"[\u4e00-\u9fa5a-zA-Z0-9\U0001F300-\U0001FAFF\U00002600-\U000027BF-—·()（）?？]+"
ROLE_DETAIL_PATTERN = (
    rf"^(?P<char_name>{PATTERN})(?:面板|信息|详情|面包|🍞)"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_1>{PATTERN}))?"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_2>{PATTERN}))?$"
)


def _service(request: CommandRequest) -> PlayerService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.PLAYER_CONTEXT_UNAVAILABLE)
    service = request.services.get("player_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in ("role_overview", "role_detail", "original_image")
    ):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return cast(PlayerService, service)


def _player_request(request: CommandRequest, parameters: dict[str, Any] | None = None) -> PlayerCommandRequest:
    assert request.actor is not None
    return PlayerCommandRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters if parameters is None else parameters),
        reply_id=request.reply_id,
    )


async def player_role_overview_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.role_overview(_player_request(request, parameters))


async def player_role_detail_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.role_detail(_player_request(request, parameters))


async def player_original_image_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.original_image(_player_request(request, parameters))


COMMAND_SPECS = (
    CommandSpec(
        id="role_info_card",
        pattern=r"^(?:查询|卡片|角色|信息)$",
        group="信息查询",
        name="基本信息卡片",
        description="查询基本信息",
        examples=("卡片",),
        permission="user",
        use_case=cast(Any, player_role_overview_use_case),
    ),
    CommandSpec(
        id="role_detail_card",
        pattern=ROLE_DETAIL_PATTERN,
        group="角色信息",
        name="角色详情卡片",
        description="查询角色面板/伤害详情",
        examples=("角色名面板",),
        permission="user",
        use_case=cast(Any, player_role_detail_use_case),
    ),
    CommandSpec(
        id="role_original_image",
        pattern=r"^原图$",
        group="角色信息",
        name="角色原图（暂不支持）",
        description="当前平台暂不支持通过引用获取角色原图",
        examples=("原图",),
        permission="user",
        use_case=cast(Any, player_original_image_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "PATTERN",
    "ROLE_DETAIL_PATTERN",
    "player_original_image_use_case",
    "player_role_detail_use_case",
    "player_role_overview_use_case",
]
