"""签到命令声明和 typed service 适配。"""

from __future__ import annotations

from typing import Any, cast

from ...entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ...entry.response import PlainTextResponse
from . import messages
from .contracts import CheckinCommandRequest
from .service import CheckinService


def _service(
    request: CommandRequest,
    *,
    required_methods: tuple[str, ...] = (),
) -> CheckinService | PlainTextResponse:
    if request.actor is None:
        return PlainTextResponse(messages.CHECKIN_CONTEXT_UNAVAILABLE)
    service = request.services.get("checkin_service")
    if service is None or not all(
        callable(getattr(service, method, None))
        for method in (
            "manual_sign",
            "sign_calendar",
            "sign_all",
            "subscribe_sign_result",
            "set_auto_sign",
            *required_methods,
        )
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


async def checkin_sign_group_report_subscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request, required_methods=("subscribe_group_report",))
    if isinstance(service, PlainTextResponse):
        return service
    return await service.subscribe_group_report(_checkin_request(request))


async def checkin_auto_sign_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.set_auto_sign(
        _checkin_request(request),
        enabled=(
            bool(parameters["enabled"])
            if "enabled" in parameters
            else request.command_id == "sign_auto_enable" or "开启" in request.text
        ),
    )


COMMAND_SPECS = (
    CommandSpec(
        id="sign",
        pattern=r"^(?:签到|社区签到|每日任务|社区任务|库街区签到|sign)$",
        group="签到服务",
        name="签到",
        description="每日签到",
        examples=("签到",),
        permission="user",
        use_case=cast(Any, checkin_sign_use_case),
    ),
    CommandSpec(
        id="sign_calendar",
        pattern=r"^(?:签到日历|签到记录|签到历史)$",
        group="签到服务",
        name="签到日历",
        description="查看签到日历",
        examples=("签到日历",),
        permission="user",
        use_case=cast(Any, checkin_sign_calendar_use_case),
        mention_policy="query",
    ),
    CommandSpec(
        id="sign_auto_enable",
        pattern=r"^开启自动签到$",
        group="签到服务",
        name="开启自动签到",
        description="开启当前 UID 的自动签到",
        examples=("开启自动签到",),
        permission="user",
        use_case=cast(Any, checkin_auto_sign_use_case),
    ),
    CommandSpec(
        id="sign_auto_disable",
        pattern=r"^关闭自动签到$",
        group="签到服务",
        name="关闭自动签到",
        description="关闭当前 UID 的自动签到",
        examples=("关闭自动签到",),
        permission="user",
        use_case=cast(Any, checkin_auto_sign_use_case),
    ),
    CommandSpec(
        id="sign_all",
        pattern=r"^全部签到$",
        group="bot主人功能",
        name="全部签到",
        description="手动触发全部账号签到",
        examples=("全部签到",),
        permission="admin",
        use_case=cast(Any, checkin_sign_all_use_case),
    ),
    CommandSpec(
        id="sign_result_subscribe",
        pattern=r"^(订阅|取消订阅)签到结果$",
        group="bot主人功能",
        name="订阅签到结果",
        description="订阅/取消订阅签到结果推送",
        examples=("订阅签到结果",),
        permission="admin",
        use_case=cast(Any, checkin_sign_result_subscribe_use_case),
    ),
    CommandSpec(
        id="sign_group_report_subscribe",
        pattern=r"^(订阅|取消订阅)本群签到报告$",
        group="bot主人功能",
        name="订阅本群签到报告",
        description="订阅/取消订阅当前群的独立签到报告",
        examples=("订阅本群签到报告",),
        permission="admin",
        use_case=cast(Any, checkin_sign_group_report_subscribe_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "checkin_auto_sign_use_case",
    "checkin_sign_all_use_case",
    "checkin_sign_calendar_use_case",
    "checkin_sign_group_report_subscribe_use_case",
    "checkin_sign_result_subscribe_use_case",
    "checkin_sign_use_case",
]
