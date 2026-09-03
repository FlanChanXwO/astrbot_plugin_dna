"""玩家查询命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import PlayerCommandRequest
from .service import PlayerService

PATTERN = (
    r"[\u4e00-\u9fa5a-zA-Z0-9\U0001F300-\U0001FAFF\U00002600-\U000027BF-—·()（）?？]+"
)
ROLE_DETAIL_PATTERN = (
    rf"^(?P<char_name>(?!(?:刷新|清理)){PATTERN})(?:面板|信息|详情|面包|🍞)"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_1>{PATTERN}))?"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_2>{PATTERN}))?$"
)
REFRESH_ROLE_PATTERN = rf"^刷新(?P<char_name>(?!全部角色面板$|\d+的){PATTERN})面板$"
REFRESH_ALL_ROLE_PATTERN = r"^刷新全部角色面板$"
CLEAR_ROLE_PATTERN = rf"^清理(?P<char_name>{PATTERN})面板缓存$"
CLEAR_ALL_ROLE_PATTERN = r"^清理全部角色缓存$"
REFRESH_ADMIN_ROLE_PATTERN = rf"^刷新(?P<uid>\d+)的(?P<char_name>{PATTERN})面板$"


def _service(request: CommandRequest) -> PlayerService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.PLAYER_CONTEXT_UNAVAILABLE)
    service = request.services.get("player_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in ("role_overview", "role_detail")
    ):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return cast(PlayerService, service)


def _player_request(
    request: CommandRequest, parameters: dict[str, Any] | None = None
) -> PlayerCommandRequest:
    assert request.actor is not None
    return PlayerCommandRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters if parameters is None else parameters),
        reply_id=request.reply_id,
    )


def _refresh_service(request: CommandRequest) -> PlayerService | PlainTextResponse:
    """检查缓存刷新入口；权限仍由命令声明和本函数双重约束。"""

    if request.actor is None:
        return PlainTextResponse(messages.PLAYER_CONTEXT_UNAVAILABLE)
    service = request.services.get("player_service")
    if service is None or not callable(getattr(service, "refresh_role", None)):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return cast(PlayerService, service)


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


async def player_refresh_role_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _refresh_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.refresh_role(_player_request(request, parameters))


async def player_refresh_all_roles_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _refresh_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    operation = getattr(service, "refresh_all_roles", None)
    if not callable(operation):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return await operation(_player_request(request, parameters))


async def player_refresh_admin_role_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    if request.permission != "admin":
        return PlainTextResponse(messages.PLAYER_ADMIN_ONLY)
    service = _refresh_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.refresh_role(
        _player_request(request, parameters),
        uid=str(parameters.get("uid", "")),
    )


async def player_clear_all_cache_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _refresh_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    operation = getattr(service, "clear_all_role_cache", None)
    if not callable(operation):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return await operation(_player_request(request))


async def player_clear_role_cache_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _refresh_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    operation = getattr(service, "clear_role_cache", None)
    if not callable(operation):
        return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
    return await operation(_player_request(request, parameters))


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
        mention_policy="query",
    ),
    CommandSpec(
        id="refresh_admin_role_card",
        pattern=REFRESH_ADMIN_ROLE_PATTERN,
        group="角色信息",
        name="刷新指定角色面板",
        description="管理员按游戏 UID 刷新角色面板",
        examples=("刷新123456的角色名面板",),
        permission="admin",
        use_case=cast(Any, player_refresh_admin_role_use_case),
    ),
    CommandSpec(
        id="refresh_role_card",
        pattern=REFRESH_ROLE_PATTERN,
        group="角色信息",
        name="刷新角色面板",
        description="刷新自己的指定角色面板",
        examples=("刷新角色名面板",),
        permission="user",
        use_case=cast(Any, player_refresh_role_use_case),
    ),
    CommandSpec(
        id="refresh_all_role_cards",
        pattern=REFRESH_ALL_ROLE_PATTERN,
        group="角色信息",
        name="刷新全部角色面板",
        description="刷新当前 UID 的全部已解锁角色面板数据",
        examples=("刷新全部角色面板",),
        permission="user",
        use_case=cast(Any, player_refresh_all_roles_use_case),
    ),
    CommandSpec(
        id="clear_role_cache",
        pattern=CLEAR_ROLE_PATTERN,
        group="角色信息",
        name="清理角色面板缓存",
        description="清理当前 UID 指定角色的面板缓存",
        examples=("清理菲娜面板缓存",),
        permission="user",
        use_case=cast(Any, player_clear_role_cache_use_case),
    ),
    CommandSpec(
        id="clear_player_cache",
        pattern=CLEAR_ALL_ROLE_PATTERN,
        group="角色信息",
        name="清理角色缓存",
        description="清理当前 UID 的全部角色数据和卡片缓存",
        examples=("清理全部角色缓存",),
        permission="user",
        use_case=cast(Any, player_clear_all_cache_use_case),
    ),
    CommandSpec(
        id="role_detail_card",
        pattern=ROLE_DETAIL_PATTERN,
        group="角色信息",
        name="角色详情卡片",
        description="查询角色和武器基础详情，不包含伤害计算",
        examples=("角色名面板",),
        permission="user",
        use_case=cast(Any, player_role_detail_use_case),
        mention_policy="query",
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
        mention_policy="query",
    ),
)


__all__ = [
    "CLEAR_ALL_ROLE_PATTERN",
    "CLEAR_ROLE_PATTERN",
    "COMMAND_SPECS",
    "PATTERN",
    "REFRESH_ADMIN_ROLE_PATTERN",
    "REFRESH_ALL_ROLE_PATTERN",
    "REFRESH_ROLE_PATTERN",
    "ROLE_DETAIL_PATTERN",
    "player_clear_all_cache_use_case",
    "player_clear_role_cache_use_case",
    "player_original_image_use_case",
    "player_refresh_admin_role_use_case",
    "player_refresh_all_roles_use_case",
    "player_refresh_role_use_case",
    "player_role_detail_use_case",
    "player_role_overview_use_case",
]
