from ..utils.session import EventContext, Sender
from .draw_calendar_card import draw_calendar_img


async def handle_calendar(sender: Sender, ctx: EventContext):
    """日历：查询活动日历。"""
    im = await draw_calendar_img(ctx)
    sender.send(im)


COMMANDS = [
    {
        "key": "calendar",
        "group": "信息查询",
        "name": "日历",
        "desc": "日历",
        "eg": "日历",
        "regex": r"^日历$",
        "permission": "user",
        "handler": handle_calendar,
    },
]
