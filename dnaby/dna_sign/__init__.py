from astrbot.api import logger

from ..dna_config.dna_config import DNASignConfig
from ..utils.constants.boardcast import BoardcastTypeEnum
from ..utils.database.models import DNASign
from ..utils.msgs.notify import send_dna_text
from ..utils.session import EventContext, Sender
from ..utils.subscriptions import gs_subscribe
from ..utils.utils import get_two_days_ago_date
from .draw_sign import draw_sign_calendar
from .sign import auto_sign, manual_sign

SIGN_TIME = DNASignConfig.get_config("SignTime").data
try:
    if isinstance(SIGN_TIME, tuple):
        int_hour, int_minute = SIGN_TIME
        if int_hour < 0 or int_hour > 23 or int_minute < 0 or int_minute > 59:
            int_hour, int_minute = 0, 5
        hour, minute = str(int_hour), str(int_minute)
    else:
        hour, minute = SIGN_TIME.split(":")
        int_hour = int(hour)
        int_minute = int(minute)
        if int_hour < 0 or int_hour > 23 or int_minute < 0 or int_minute > 59:
            hour = "0"
            minute = "5"
except (ValueError, TypeError):
    hour = "0"
    minute = "5"


async def handle_dna_user_sign(sender: Sender, ctx: EventContext):
    await manual_sign(sender, ctx)


async def handle_sign_calendar(sender: Sender, ctx: EventContext):
    await draw_sign_calendar(sender, ctx)


async def handle_sign_recheck_all(sender: Sender, ctx: EventContext):
    await send_dna_text(sender, ctx, "[DNAUID] [全部签到] 已开始执行!")
    msg = await auto_sign()
    await send_dna_text(sender, ctx, "[DNAUID] [全部签到] 执行完成!")
    await send_dna_text(sender, ctx, msg)


async def handle_sign_result(sender: Sender, ctx: EventContext):
    if "取消" in ctx.raw_text:
        option = "关闭"
    else:
        option = "开启"

    if option == "关闭":
        await gs_subscribe.delete_subscribe("single", BoardcastTypeEnum.SIGN_RESULT, ctx)
    else:
        await gs_subscribe.add_subscribe("single", BoardcastTypeEnum.SIGN_RESULT, ctx)

    await send_dna_text(sender, ctx, f"[DNAUID] [订阅签到结果] 已{option}订阅!")


async def dna_auto_sign():
    msg = await auto_sign()
    subscribes = await gs_subscribe.get_subscribe(BoardcastTypeEnum.SIGN_RESULT)
    if subscribes:
        logger.info(f"[DNAUID]推送主人签到结果: {msg}")
        for sub in subscribes:
            await sub.send(msg)


async def clear_dna_sign_record():
    """清除2天前的签到记录"""
    await DNASign.clear_sign_record(get_two_days_ago_date())
    logger.info("[DNAUID] [清除签到记录] 已清除2天前的签到记录!")


COMMANDS = [
    {
        "key": "sign",
        "group": "签到",
        "name": "签到",
        "desc": "每日签到",
        "eg": "签到",
        "regex": r"^(?:签到|社区签到|每日任务|社区任务|库街区签到|sign)$",
        "permission": "user",
        "handler": handle_dna_user_sign,
    },
    {
        "key": "sign_calendar",
        "group": "签到",
        "name": "签到日历",
        "desc": "查看签到日历",
        "eg": "签到日历",
        "regex": r"^(?:签到日历|签到记录|签到历史)$",
        "permission": "user",
        "handler": handle_sign_calendar,
    },
    {
        "key": "sign_all",
        "group": "签到",
        "name": "全部签到",
        "desc": "手动触发全部账号签到",
        "eg": "全部签到",
        "regex": r"^全部签到$",
        "permission": "owner",
        "handler": handle_sign_recheck_all,
    },
    {
        "key": "sign_result_subscribe",
        "group": "签到",
        "name": "订阅签到结果",
        "desc": "订阅/取消订阅签到结果推送",
        "eg": "订阅签到结果",
        "regex": r"^(订阅|取消订阅)签到结果$",
        "permission": "owner",
        "handler": handle_sign_result,
    },
]
