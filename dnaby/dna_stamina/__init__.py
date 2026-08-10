from ..utils.session import EventContext, Sender
from .draw_stamina import draw_stamina_img


async def handle_stamina(sender: Sender, ctx: EventContext):
    """日常便签：查询实时便笺 / 体力。"""
    await draw_stamina_img(sender, ctx)


COMMANDS = [
    {
        "key": "stamina",
        "group": "信息查询",
        "name": "日常便签",
        "desc": "查询实时便笺/体力",
        "eg": "日常",
        "regex": r"^(?:每日|mr|实时便笺|便笺|便签|体力|日常|日常便签)$",
        "permission": "user",
        "handler": handle_stamina,
    },
]
