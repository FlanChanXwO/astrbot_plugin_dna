from ..utils.session import EventContext, Sender
from .draw_role_info_card import draw_role_info_card


async def handle_role_info_card(sender: Sender, ctx: EventContext):
    """基本信息卡片：查询/卡片/角色/信息。"""
    await draw_role_info_card(sender, ctx)


COMMANDS = [
    {
        "key": "role_info_card",
        "group": "信息查询",
        "name": "基本信息卡片",
        "desc": "查询基本信息",
        "eg": "卡片",
        "regex": r"^(?:查询|卡片|角色|信息)$",
        "permission": "user",
        "handler": handle_role_info_card,
    },
]
