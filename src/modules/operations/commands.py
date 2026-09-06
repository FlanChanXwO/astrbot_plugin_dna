"""资源同步命令声明。

自定义面板图管理已经从公开命令面移除；标准面板资源只由资源协调器提供给
普通角色卡片，不能通过聊天命令上传、列出或删除。
"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .resource_service import ResourceUpdateService


def _resource_service(
    request: CommandRequest,
) -> ResourceUpdateService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.OPERATIONS_CONTEXT_UNAVAILABLE)
    service = request.services.get("resource_update_service")
    if service is None:
        return PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)
    return cast(ResourceUpdateService, service)


async def resource_status_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _resource_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    operation = getattr(service, "status", None)
    if not callable(operation):
        return PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)
    return await operation()


async def resource_download_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _resource_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.sync_resources(None)


COMMAND_SPECS = (
    CommandSpec(
        id="resource_status",
        pattern=r"^资源状态$",
        group="资源管理",
        name="资源状态",
        description="查看公共资源仓库状态",
        examples=("资源状态",),
        permission="admin",
        use_case=cast(Any, resource_status_use_case),
    ),
    CommandSpec(
        id="download_resource",
        pattern=r"^同步资源$",
        group="资源管理",
        name="同步资源",
        description="同步全部公共资源",
        examples=("同步资源",),
        permission="admin",
        use_case=cast(Any, resource_download_use_case),
    ),
)


__all__ = ["COMMAND_SPECS", "resource_download_use_case", "resource_status_use_case"]
