from ..utils.session import EventContext, Sender
from .get_help import get_help


async def handle_help(sender: Sender, ctx: EventContext):
    """帮助：渲染帮助卡片。"""
    im = await get_help()
    sender.send_option(im)


COMMANDS = [
    {
        "key": "help",
        "group": "bot主人功能",
        "name": "帮助",
        "desc": "查看帮助",
        "eg": "帮助",
        "regex": r"^帮助$",
        "permission": "user",
        "handler": handle_help,
    },
]
