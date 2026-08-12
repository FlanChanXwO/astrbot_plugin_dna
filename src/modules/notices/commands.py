"""密函与公告命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import NoticeRequest
from .service import NoticesService


def _service(request: CommandRequest) -> NoticesService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.NOTICES_CONTEXT_UNAVAILABLE)
    service = request.services.get("notices_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in ("mh", "mh_list", "ann")
    ):
        return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
    return cast(NoticesService, service)


def _notice_request(request: CommandRequest) -> NoticeRequest:
    assert request.actor is not None
    return NoticeRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters),
        text=request.text,
    )


async def notices_mh_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.mh(_notice_request(request))


async def notices_mh_list_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.mh_list(_notice_request(request))


async def notices_ann_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.ann(_notice_request(request))


COMMAND_SPECS = (
    CommandSpec(
        id="mh",
        pattern=r"^(?:密函|委托密函|mh)$",
        group="密函",
        name="密函",
        description="查看当前小时段密函委托",
        examples=("密函",),
        permission="user",
        use_case=cast(Any, notices_mh_use_case),
    ),
    CommandSpec(
        id="mh_list",
        pattern=r"^密函列表$",
        group="密函",
        name="密函列表",
        description="查看全部密函委托名称",
        examples=("密函列表",),
        permission="user",
        use_case=cast(Any, notices_mh_list_use_case),
    ),
    CommandSpec(
        id="ann",
        pattern=r"^公告(?:\s+(?P<index>\d+))?$",
        group="公告",
        name="公告",
        description="查看公告列表；带序号时查看公告详情",
        examples=("公告", "公告 1"),
        permission="user",
        use_case=cast(Any, notices_ann_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "notices_ann_use_case",
    "notices_mh_list_use_case",
    "notices_mh_use_case",
]
