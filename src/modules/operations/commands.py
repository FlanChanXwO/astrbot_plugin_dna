"""面板图管理与资源状态命令声明和 typed service 适配。"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from ..player.commands import PATTERN
from . import messages
from .resource_service import ResourceUpdateService
from .service import PanelCommandRequest, PanelService


def _service(request: CommandRequest) -> PanelService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.OPERATIONS_CONTEXT_UNAVAILABLE)
    service = request.services.get("panel_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in (
            "upload_panel_img",
            "list_panel_imgs",
            "delete_panel_img_by_id",
            "delete_all_panel_imgs",
            "delete_original_panel_img",
            "compress_panel_imgs",
            "resource_status",
        )
    ):
        return PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)
    return cast(PanelService, service)


def _panel_request(request: CommandRequest) -> PanelCommandRequest:
    assert request.actor is not None
    return PanelCommandRequest(
        actor=request.actor,
        parameters={key: str(value) for key, value in request.parameters.items()},
        text=request.text,
        images=request.images,
    )


async def _call(request: CommandRequest, method: str):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    operation = getattr(service, method, None)
    if not callable(operation):
        return PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)
    return await cast(Awaitable, operation(_panel_request(request)))


async def panel_upload_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "upload_panel_img")


async def panel_list_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "list_panel_imgs")


async def panel_delete_by_id_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "delete_panel_img_by_id")


async def panel_delete_all_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "delete_all_panel_imgs")


async def panel_delete_original_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "delete_original_panel_img")


async def panel_compress_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "compress_panel_imgs")


async def panel_resource_status_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    return await _call(request, "resource_status")


def _resource_service(request: CommandRequest) -> ResourceUpdateService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.OPERATIONS_CONTEXT_UNAVAILABLE)
    service = request.services.get("resource_update_service")
    if service is None or not callable(getattr(service, "download_all", None)):
        return PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)
    return cast(ResourceUpdateService, service)


async def resource_download_use_case(request: CommandRequest, _registry: CommandRegistry, **_parameters: Any):
    service = _resource_service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.download_all(None)


_COMMON = {
    "group": "面板图管理",
    "permission": "admin",
}

COMMAND_SPECS = (
    CommandSpec(
        id="upload_panel_img",
        pattern=rf"^上传(?P<char_name>{PATTERN})面板图$",
        name="上传面板图",
        description="上传角色自定义面板图",
        examples=("上传角色面板图",),
        use_case=cast(Any, panel_upload_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="list_panel_imgs",
        pattern=rf"^(?P<char_name>{PATTERN})面板图列表$",
        name="面板图列表",
        description="查看角色已上传的面板图",
        examples=("角色面板图列表",),
        use_case=cast(Any, panel_list_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="delete_panel_img_by_id",
        pattern=rf"^删除(?P<char_name>{PATTERN})面板图(?P<image_id>\S+)$",
        name="删除面板图",
        description="按 ID 删除角色面板图",
        examples=("删除角色面板图abc",),
        use_case=cast(Any, panel_delete_by_id_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="delete_all_panel_imgs",
        pattern=rf"^删除(?P<char_name>{PATTERN})全部面板图$",
        name="删除全部面板图",
        description="删除角色全部面板图",
        examples=("删除角色全部面板图",),
        use_case=cast(Any, panel_delete_all_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="delete_original_panel_img",
        pattern=r"^原图删除$",
        name="删除原图",
        description="删除引用面板图对应的原图",
        examples=("原图删除",),
        use_case=cast(Any, panel_delete_original_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="compress_panel_imgs",
        pattern=r"^压缩面板图$",
        name="压缩面板图",
        description="压缩全部自定义面板图",
        examples=("压缩面板图",),
        use_case=cast(Any, panel_compress_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="resource_status",
        pattern=r"^资源状态$",
        name="资源状态",
        description="查看公共资源仓库与自定义面板状态",
        examples=("资源状态",),
        use_case=cast(Any, panel_resource_status_use_case),
        **_COMMON,
    ),
    CommandSpec(
        id="download_resource",
        pattern=r"^下载全部资源$",
        group="资源管理",
        name="下载全部资源",
        description="下载全部资源",
        examples=("下载全部资源",),
        permission="admin",
        use_case=cast(Any, resource_download_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "panel_compress_use_case",
    "panel_delete_all_use_case",
    "panel_delete_by_id_use_case",
    "panel_delete_original_use_case",
    "panel_list_use_case",
    "panel_resource_status_use_case",
    "panel_upload_use_case",
    "resource_download_use_case",
]
