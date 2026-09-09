"""客户端更新命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import ClientUpdateRequest


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


async def client_update_query_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    del parameters
    service = _service(request, "query")
    if isinstance(service, PlainTextResponse):
        return service
    return await cast(Any, service).query(ClientUpdateRequest(actor=request.actor))


async def client_update_subscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    del parameters
    guard_error = _admin_group_guard(request, unsubscribe=False)
    if guard_error is not None:
        return guard_error
    service = _service(request, "subscribe")
    if isinstance(service, PlainTextResponse):
        return service
    return await cast(Any, service).subscribe(ClientUpdateRequest(actor=request.actor))


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
    return await cast(Any, service).unsubscribe(
        ClientUpdateRequest(actor=request.actor)
    )


COMMAND_SPECS = (
    CommandSpec(
        id="client_update",
        pattern=r"^客户端更新$",
        group="信息查询",
        name="客户端更新",
        description="查询已配置目标的客户端版本更新",
        examples=("客户端更新",),
        permission="user",
        use_case=cast(Any, client_update_query_use_case),
        mention_policy="query",
    ),
    CommandSpec(
        id="client_update_subscribe",
        pattern=r"^订阅客户端更新$",
        group="信息查询",
        name="订阅客户端更新",
        description="订阅群聊中的客户端更新推送",
        examples=("订阅客户端更新",),
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
