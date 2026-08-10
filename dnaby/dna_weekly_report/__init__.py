from ..utils.session import EventContext, Sender
from .draw_weekly_report import draw_weekly_report_img


async def handle_weekly_report_current(sender: Sender, ctx: EventContext):
    """本周周报：查询本周资源获取统计。"""
    await draw_weekly_report_img(sender, ctx, week_type=1)


async def handle_weekly_report_last(sender: Sender, ctx: EventContext):
    """上周周报：查询上周资源获取统计。"""
    await draw_weekly_report_img(sender, ctx, week_type=2)


COMMANDS = [
    {
        "key": "weekly_report_current",
        "group": "信息查询",
        "name": "本周周报",
        "desc": "查询本周资源获取统计",
        "eg": "周报",
        "regex": r"^(?:本周周报|周报)$",
        "permission": "user",
        "handler": handle_weekly_report_current,
    },
    {
        "key": "weekly_report_last",
        "group": "信息查询",
        "name": "上周周报",
        "desc": "查询上周资源获取统计",
        "eg": "上周周报",
        "regex": r"^上周周报$",
        "permission": "user",
        "handler": handle_weekly_report_last,
    },
]
