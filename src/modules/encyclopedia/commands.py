"""资料查询命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from ..agent_tools import queries
from ..agent_tools.contracts import AgentQueryRequest
from ..player.commands import PATTERN
from . import messages
from .contracts import EncyclopediaRequest
from .service import EncyclopediaService


def _service(request: CommandRequest) -> EncyclopediaService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.CONTEXT_UNAVAILABLE)
    service = request.services.get("encyclopedia_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in (
            "stamina",
            "weekly_report",
            "calendar",
            "wiki",
            "guide",
            "codes",
            "alias_list",
            "alias_all_list",
        )
    ):
        return PlainTextResponse(messages.SERVICE_UNAVAILABLE)
    return cast(EncyclopediaService, service)


def _request(request: CommandRequest, parameters: dict[str, Any] | None = None) -> EncyclopediaRequest:
    assert request.actor is not None
    return EncyclopediaRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters if parameters is None else parameters),
        text=request.text,
    )


async def stamina_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    assert request.actor is not None
    return await queries.stamina_query(
        service,
        AgentQueryRequest(
            actor=request.actor,
            target_user_id=request.target_user_id,
            parameters=parameters,
            text=request.text,
        ),
    )


async def weekly_report_current_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    parameters["week_type"] = 1
    return await service.weekly_report(_request(request, parameters))


async def weekly_report_last_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    parameters["week_type"] = 2
    return await service.weekly_report(_request(request, parameters))


async def calendar_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.calendar(_request(request, parameters))


async def wiki_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.wiki(_request(request, parameters))


async def guide_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.guide(_request(request, parameters))


async def code_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.codes(_request(request, parameters))


async def alias_list_use_case(request: CommandRequest, _registry: CommandRegistry, **parameters: Any):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.alias_list(_request(request, parameters))


async def alias_all_list_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.alias_all_list(_request(request, parameters))


COMMAND_SPECS = (
    CommandSpec(
        id="stamina",
        pattern=r"^(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$",
        group="信息查询",
        name="日常便签",
        description="查询实时便笺/体力",
        examples=("日常",),
        permission="user",
        use_case=cast(Any, stamina_use_case),
    ),
    CommandSpec(
        id="weekly_report_current",
        pattern=r"^(?:本周周报|周报)$",
        group="信息查询",
        name="本周周报",
        description="查询本周资源获取统计",
        examples=("周报",),
        permission="user",
        use_case=cast(Any, weekly_report_current_use_case),
    ),
    CommandSpec(
        id="weekly_report_last",
        pattern=r"^上周周报$",
        group="信息查询",
        name="上周周报",
        description="查询上周资源获取统计",
        examples=("上周周报",),
        permission="user",
        use_case=cast(Any, weekly_report_last_use_case),
    ),
    CommandSpec(
        id="calendar",
        pattern=r"^日历$",
        group="信息查询",
        name="日历",
        description="日历",
        examples=("日历",),
        permission="user",
        use_case=cast(Any, calendar_use_case),
    ),
    CommandSpec(
        id="dna_wiki",
        pattern=rf"^(?P<name>{PATTERN})(?:图鉴|wiki|Wiki|WIKI)$",
        group="图鉴",
        name="角色图鉴",
        description="查看角色图鉴",
        examples=("角色名图鉴",),
        permission="user",
        use_case=cast(Any, wiki_use_case),
    ),
    CommandSpec(
        id="dna_guide",
        pattern=rf"^(?P<char_name>{PATTERN})攻略$",
        group="攻略",
        name="角色攻略",
        description="查看角色攻略图",
        examples=("角色名攻略",),
        permission="user",
        use_case=cast(Any, guide_use_case),
    ),
    CommandSpec(
        id="dna_code",
        pattern=r"^(?:兑换码|cdk|CDK|code)$",
        group="兑换码",
        name="兑换码",
        description="查看当前可用的兑换码",
        examples=("兑换码",),
        permission="user",
        use_case=cast(Any, code_use_case),
    ),
    CommandSpec(
        id="alias_list",
        pattern=rf"^(?!添加|删除|恢复|强制恢复)(?P<alias_type>角色|武器)?(?P<name>{PATTERN})别名(列表)?$",
        group="bot主人功能",
        name="别名列表",
        description="查看角色/武器别名列表",
        examples=("角色名别名",),
        permission="admin",
        use_case=cast(Any, alias_list_use_case),
    ),
    CommandSpec(
        id="alias_all_list",
        pattern=r"^(?:角色列表|武器列表)$",
        group="bot主人功能",
        name="角色/武器列表",
        description="查看全部角色或武器列表",
        examples=("角色列表",),
        permission="user",
        use_case=cast(Any, alias_all_list_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "calendar_use_case",
    "code_use_case",
    "guide_use_case",
    "stamina_use_case",
    "weekly_report_current_use_case",
    "weekly_report_last_use_case",
    "wiki_use_case",
]
