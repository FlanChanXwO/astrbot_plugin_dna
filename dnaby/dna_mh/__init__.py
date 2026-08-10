from ..dna_config.dna_config import DNAConfig
from ..utils.api.mh_map import get_mh_list
from ..utils.msgs.notify import send_dna_notify, send_dna_text
from ..utils.session import EventContext, Sender
from .draw_mh import draw_mh
from .push_mh import send_mh_notify
from .subscribe_mh import (
    get_mh_subscribe,
    subscribe_mh,
    subscribe_mh_pic,
    subscribe_mh_text,
    subscribe_mh_time,
)

RE_MH_LIST = "|".join(get_mh_list()) + "|全部"
RE_MH_TYPE_LIST = "角色|武器|魔之楔"

MHPUSH_TIME = DNAConfig.get_config("MHPushSubscribe").data
try:
    minute, second = MHPUSH_TIME.split(":")
    int_minute = int(minute)
    int_second = int(second)
    if int_minute < 0 or int_minute > 59 or int_second < 0 or int_second > 59:
        minute = "0"
        second = "5"
except ValueError:
    minute = "0"
    second = "5"


async def handle_send_mh(sender: Sender, ctx: EventContext):
    return await draw_mh(sender, ctx)


async def handle_send_mh_list(sender: Sender, ctx: EventContext):
    await send_dna_text(sender, ctx, "\n".join(get_mh_list()))


async def handle_dna_mh_subscribe(sender: Sender, ctx: EventContext):
    mh_type = ctx.regex_dict.get("mh_type")
    mh_name = ctx.regex_dict.get("mh_name")
    if not mh_name:
        return

    await subscribe_mh(sender, ctx, mh_name, mh_type)


async def handle_dna_mh_push_time(sender: Sender, ctx: EventContext):
    from ..dna_config import DNA_PREFIX

    msg = [
        "设置推送时间段格式错误，请使用以下格式",
        f"例如开始时间:17点, 结束时间:23点, 命令: {DNA_PREFIX}订阅密函时间17:23",
    ]
    msg = "\n".join(msg)

    _, start_hour, end_hour = ctx.regex_group
    start_hour = int(start_hour)
    end_hour = int(end_hour)

    if (start_hour < 0 or start_hour > 23) or (end_hour < 0 or end_hour > 23):
        await send_dna_notify(sender, ctx, msg)
        return

    await subscribe_mh_time(sender, ctx, ctx.user_id, start_hour, end_hour)


async def handle_sub_mh_pic_subscribe(sender: Sender, ctx: EventContext):
    await subscribe_mh_pic(sender, ctx)


async def handle_sub_mh_text_subscribe(sender: Sender, ctx: EventContext):
    await subscribe_mh_text(sender, ctx)


async def handle_send_mh_subscribe(sender: Sender, ctx: EventContext):
    await get_mh_subscribe(sender, ctx)


async def dna_push_mh_notify():
    await send_mh_notify()


async def handle_send_mh_test(sender: Sender, ctx: EventContext):
    await send_mh_notify()


COMMANDS = [
    {
        "key": "mh",
        "group": "密函",
        "name": "密函",
        "desc": "查看当前密函",
        "eg": "密函",
        "regex": r"^(?:密函|委托密函|mh)$",
        "permission": "user",
        "handler": handle_send_mh,
    },
    {
        "key": "mh_list",
        "group": "密函",
        "name": "密函列表",
        "desc": "查看可订阅密函列表",
        "eg": "密函列表",
        "regex": r"^密函列表$",
        "permission": "user",
        "handler": handle_send_mh_list,
    },
    {
        "key": "mh_subscribe",
        "group": "密函",
        "name": "我的密函订阅",
        "desc": "查看我的密函订阅",
        "eg": "我的密函",
        "regex": r"^(?:密函订阅|我的密函|我的密函订阅)$",
        "permission": "user",
        "handler": handle_send_mh_subscribe,
    },
    {
        "key": "mh_subscribe_by_name",
        "group": "密函",
        "name": "订阅密函",
        "desc": "订阅/取消订阅指定密函",
        "eg": "订阅角色驱逐密函",
        "regex": rf"^(订阅|取消订阅)(?P<mh_type>{RE_MH_TYPE_LIST})?(?P<mh_name>{RE_MH_LIST})密函$",
        "permission": "user",
        "handler": handle_dna_mh_subscribe,
    },
    {
        "key": "mh_subscribe_cycle",
        "group": "密函",
        "name": "订阅密函时间/周期",
        "desc": "设置密函推送时间段",
        "eg": "订阅密函时间17:23",
        "regex": r"^订阅密函(时间|周期)(\d{1,2}):(\d{1,2})$",
        "permission": "user",
        "handler": handle_dna_mh_push_time,
    },
    {
        "key": "mh_pic_subscribe",
        "group": "密函",
        "name": "订阅密函图片",
        "desc": "订阅/取消订阅密函图片推送",
        "eg": "订阅密函图片",
        "regex": r"^(?:订阅密函图片|取消订阅密函图片)$",
        "permission": "admin",
        "handler": handle_sub_mh_pic_subscribe,
    },
    {
        "key": "mh_text_subscribe",
        "group": "密函",
        "name": "订阅密函文本",
        "desc": "订阅/取消订阅密函文本推送",
        "eg": "订阅密函文本",
        "regex": r"^(?:订阅密函文本|取消订阅密函文本)$",
        "permission": "admin",
        "handler": handle_sub_mh_text_subscribe,
    },
    {
        "key": "mh_test",
        "group": "密函",
        "name": "密函测试",
        "desc": "测试密函推送",
        "eg": "密函测试",
        "regex": r"^密函测试$",
        "permission": "owner",
        "handler": handle_send_mh_test,
    },
]
