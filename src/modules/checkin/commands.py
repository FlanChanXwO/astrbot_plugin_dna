"""签到命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import CheckinCommandRequest
from .service import CheckinService


def _service(request: CommandRequest) -> CheckinService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.CHECKIN_CONTEXT_UNAVAILABLE)
    service = request.services.get("checkin_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in ("manual_sign", "sign_calendar", "sign_all", "subscribe_sign_result")
    ):
        return PlainTextResponse(messages.CHECKIN_SERVICE_UNAVAILABLE)
    return cast(CheckinService, service)


def _checkin_request(request: CommandRequest) -> CheckinCommandRequest:
    assert request.actor is not None
    return CheckinCommandRequest(
        actor=request.actor,
        target_user_id=request.target_user_id,
        parameters=dict(request.parameters),
        text=request.text,
    )


async def checkin_sign_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.manual_sign(_checkin_request(request))


async def checkin_sign_calendar_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.sign_calendar(_checkin_request(request))


async def checkin_sign_all_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.sign_all(_checkin_request(request))


async def checkin_sign_result_subscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.subscribe_sign_result(_checkin_request(request))


COMMAND_SPECS = (
    CommandSpec(
        id="sign",
        pattern=r"^(?:签到|社区签到|每日任务|社区任务|库街区签到|sign)$",
        group="签到",
        name="签到",
        description="每日签到",
        examples=("签到",),
        permission="user",
        use_case=cast(Any, checkin_sign_use_case),
    ),
    CommandSpec(
        id="sign_calendar",
        pattern=r"^(?:签到日历|签到记录|签到历史)$",
        group="签到",
        name="签到日历",
        description="查看签到日历",
        examples=("签到日历",),
        permission="user",
        use_case=cast(Any, checkin_sign_calendar_use_case),
    ),
    CommandSpec(
        id="sign_all",
        pattern=r"^全部签到$",
        group="签到",
        name="全部签到",
        description="手动触发全部账号签到",
        examples=("全部签到",),
        permission="owner",
        use_case=cast(Any, checkin_sign_all_use_case),
    ),
    CommandSpec(
        id="sign_result_subscribe",
        pattern=r"^(订阅|取消订阅)签到结果$",
        group="签到",
        name="订阅签到结果",
        description="订阅/取消订阅签到结果推送",
        examples=("订阅签到结果",),
        permission="owner",
        use_case=cast(Any, checkin_sign_result_subscribe_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "checkin_sign_all_use_case",
    "checkin_sign_calendar_use_case",
    "checkin_sign_result_subscribe_use_case",
    "checkin_sign_use_case",
]
