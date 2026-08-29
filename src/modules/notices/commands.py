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
        for method in (
            "mh",
            "mh_list",
            "ann",
            "subscribe_mh",
            "unsubscribe_mh",
            "mh_subscriptions",
            "set_mh_push_time",
            "toggle_mh_pic",
            "toggle_mh_text",
            "test_mh_push",
            "subscribe_ann",
            "unsubscribe_ann",
        )
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
        matched_prefix=getattr(request, "matched_prefix", "kk"),
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


async def notices_mh_subscribe_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    notice = _notice_request(request)
    if "取消" in notice.text:
        return await service.unsubscribe_mh(notice)
    return await service.subscribe_mh(notice)


async def notices_mh_subscriptions_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.mh_subscriptions(_notice_request(request))


async def notices_mh_push_time_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.set_mh_push_time(_notice_request(request))


async def notices_mh_pic_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.toggle_mh_pic(_notice_request(request))


async def notices_mh_text_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.toggle_mh_text(_notice_request(request))


async def notices_mh_test_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.test_mh_push(_notice_request(request))


async def notices_ann_sub_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.subscribe_ann(_notice_request(request))


async def notices_ann_unsub_use_case(
    request: CommandRequest,
    _registry: CommandRegistry,
    **_parameters: Any,
):
    service = _service(request)
    if isinstance(service, PlainTextResponse):
        return service
    return await service.unsubscribe_ann(_notice_request(request))


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
    CommandSpec(
        id="mh_subscribe",
        pattern=r"^(?:密函订阅|我的密函|我的密函订阅)$",
        group="密函",
        name="我的密函订阅",
        description="查看当前密函订阅与推送时间",
        examples=("我的密函",),
        permission="user",
        use_case=cast(Any, notices_mh_subscriptions_use_case),
    ),
    CommandSpec(
        id="mh_subscribe_by_name",
        pattern=(
            r"^(订阅|取消订阅)"
            r"(?P<mh_type>角色|武器|魔之楔)?"
            r"(?P<mh_name>扼守|拆解|勘探|追缉|探险|调停|避险|迁移|驱逐|护送|驱离|全部)密函$"
        ),
        group="密函",
        name="订阅/取消订阅密函",
        description="按名称订阅或取消订阅密函委托",
        examples=("订阅拆解密函", "取消订阅全部密函"),
        permission="user",
        use_case=cast(Any, notices_mh_subscribe_use_case),
    ),
    CommandSpec(
        id="mh_subscribe_cycle",
        pattern=r"^订阅密函(?:时间|周期)(?P<start>\d{1,2}):(?P<end>\d{1,2})$",
        group="密函",
        name="订阅密函时间",
        description="设置密函推送时间窗口",
        examples=("订阅密函时间17:23",),
        permission="user",
        use_case=cast(Any, notices_mh_push_time_use_case),
    ),
    CommandSpec(
        id="mh_pic_subscribe",
        pattern=r"^(?:订阅密函图片|取消订阅密函图片)$",
        group="密函",
        name="订阅密函图片",
        description="订阅/取消订阅密函图片推送",
        examples=("订阅密函图片",),
        permission="admin",
        use_case=cast(Any, notices_mh_pic_use_case),
    ),
    CommandSpec(
        id="mh_text_subscribe",
        pattern=r"^(?:订阅密函文本|取消订阅密函文本)$",
        group="密函",
        name="订阅密函文本",
        description="订阅/取消订阅密函文本推送",
        examples=("订阅密函文本",),
        permission="admin",
        use_case=cast(Any, notices_mh_text_use_case),
    ),
    CommandSpec(
        id="mh_test",
        pattern=r"^密函测试$",
        group="密函",
        name="密函测试",
        description="向当前会话发送密函测试推送",
        examples=("密函测试",),
        permission="admin",
        use_case=cast(Any, notices_mh_test_use_case),
    ),
    CommandSpec(
        id="ann_sub",
        pattern=r"^订阅公告$",
        group="公告",
        name="订阅公告",
        description="订阅公告推送（群聊）",
        examples=("订阅公告",),
        permission="admin",
        use_case=cast(Any, notices_ann_sub_use_case),
    ),
    CommandSpec(
        id="ann_unsub",
        pattern=r"^(?:取消订阅公告|取消公告|退订公告)$",
        group="公告",
        name="取消订阅公告",
        description="取消订阅公告推送（群聊）",
        examples=("取消订阅公告",),
        permission="admin",
        use_case=cast(Any, notices_ann_unsub_use_case),
    ),
)


__all__ = [
    "COMMAND_SPECS",
    "notices_ann_sub_use_case",
    "notices_ann_unsub_use_case",
    "notices_ann_use_case",
    "notices_mh_list_use_case",
    "notices_mh_pic_use_case",
    "notices_mh_push_time_use_case",
    "notices_mh_subscribe_use_case",
    "notices_mh_subscriptions_use_case",
    "notices_mh_test_use_case",
    "notices_mh_text_use_case",
    "notices_mh_use_case",
]
