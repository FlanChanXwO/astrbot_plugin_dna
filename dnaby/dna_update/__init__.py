from ..utils.session import EventContext, Sender
from .draw_update_log import draw_update_log_img


async def handle_update_log(sender: Sender, ctx: EventContext):
    """更新记录：查看插件更新日志。"""
    im = await draw_update_log_img()
    sender.send(im)


COMMANDS = [
    {
        "key": "update_log",
        "group": "bot主人功能",
        "name": "git更新记录",
        "desc": "更新记录",
        "eg": "更新记录",
        "regex": r"^(?:更新记录|更新日志)$",
        "permission": "owner",
        "handler": handle_update_log,
    },
]
