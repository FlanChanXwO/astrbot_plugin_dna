"""客户端更新命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import (
    ClientPlatform,
    ClientUpdateRequest,
    normalize_client_update_platforms,
)

_DEFAULT_PLATFORMS = (ClientPlatform.PC, ClientPlatform.ANDROID)
_PLATFORM_ALIASES = {
    "PC": ClientPlatform.PC,
    "安卓": ClientPlatform.ANDROID,
}


def _service(
    request: CommandRequest,
    method: str,
) -> object | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE)
    service = request.services.get("client_update_service")
    if service is None or not callable(getattr(service, method, None)):
        return PlainTextResponse(messages.CLIENT_UPDATE_SERVICE_UNAVAILABLE)
    return service


def _admin_group_guard(
    request: CommandRequest,
    *,
    unsubscribe: bool,
) -> PlainTextResponse | None:
    if request.actor is None:
        return PlainTextResponse(
            messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE,
            need_at=True,
        )
    if request.permission != "admin":
        return PlainTextResponse(messages.CLIENT_UPDATE_ADMIN_ONLY, need_at=True)
    if not request.actor.group_id:
        message = (
            messages.CLIENT_UPDATE_GROUP_UNSUB_ONLY
            if unsubscribe
            else messages.CLIENT_UPDATE_GROUP_ONLY
        )
        return PlainTextResponse(message, need_at=True)
    return None


def _platforms(parameter: object) -> tuple[ClientPlatform, ...] | None:
    if parameter is None or not str(parameter).strip():
        return _DEFAULT_PLATFORMS
    try:
        return normalize_client_update_platforms((_PLATFORM_ALIASES[str(parameter)],))
    except (KeyError, ValueError, TypeError):
        return None


def _request(
    request: CommandRequest,
    parameters: dict[str, Any],
) -> ClientUpdateRequest | PlainTextResponse:
    selected = _platforms(parameters.get("platform"))
    if selected is None:
        return PlainTextResponse(messages.CLIENT_UPDATE_PLATFORM_INVALID, need_at=True)
    return ClientUpdateRequest(actor=request.actor, platforms=selected)


async def client_update_query_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request, "query")
    if isinstance(service, PlainTextResponse):
        return service
    client_request = _request(request, parameters)
    if isinstance(client_request, PlainTextResponse):
        return client_request
    return await cast(Any, service).query(client_request)


async def client_update_subscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    guard_error = _admin_group_guard(request, unsubscribe=False)
    if guard_error is not None:
        return guard_error
    service = _service(request, "subscribe")
    if isinstance(service, PlainTextResponse):
        return service
    client_request = _request(request, parameters)
    if isinstance(client_request, PlainTextResponse):
        return client_request
    return await cast(Any, service).subscribe(client_request)


async def client_update_unsubscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    del parameters
    guard_error = _admin_group_guard(request, unsubscribe=True)
    if guard_error is not None:
        return guard_error
    service = _service(request, "unsubscribe")
    if isinstance(service, PlainTextResponse):
        return service
    client_request = ClientUpdateRequest(
        actor=request.actor,
        platforms=_DEFAULT_PLATFORMS,
    )
    return await cast(Any, service).unsubscribe(client_request)


COMMAND_SPECS = (
    CommandSpec(
        id="client_update",
        pattern=r"^客户端更新(?:\s+(?P<platform>PC|安卓))?$",
        group="信息查询",
        name="客户端更新",
        description="查询国服 PC 与安卓客户端版本更新",
        examples=("客户端更新", "客户端更新 PC", "客户端更新 安卓"),
        permission="user",
        use_case=cast(Any, client_update_query_use_case),
        mention_policy="query",
    ),
    CommandSpec(
        id="client_update_subscribe",
        pattern=r"^订阅客户端更新(?:\s+(?P<platform>PC|安卓))?$",
        group="信息查询",
        name="订阅客户端更新",
        description="订阅群聊中的客户端更新推送",
        examples=("订阅客户端更新", "订阅客户端更新 PC", "订阅客户端更新 安卓"),
        permission="admin",
        use_case=cast(Any, client_update_subscribe_use_case),
    ),
    CommandSpec(
        id="client_update_unsubscribe",
        pattern=r"^取消订阅客户端更新$",
        group="信息查询",
        name="取消订阅客户端更新",
        description="取消当前群的客户端更新推送",
        examples=("取消订阅客户端更新",),
        permission="admin",
        use_case=cast(Any, client_update_unsubscribe_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "client_update_query_use_case",
    "client_update_subscribe_use_case",
    "client_update_unsubscribe_use_case",
]
