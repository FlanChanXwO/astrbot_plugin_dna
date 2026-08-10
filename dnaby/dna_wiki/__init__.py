from ..utils.constants.constants import PATTERN
from ..utils.session import EventContext, Sender
from .wiki import get_wiki


async def handle_wiki(sender: Sender, ctx: EventContext):
    name = ctx.regex_dict.get("name", "")
    await get_wiki(sender, ctx, name)


COMMANDS = [
    {
        "key": "dna_wiki",
        "group": "图鉴",
        "name": "角色图鉴",
        "desc": "查看角色图鉴",
        "eg": "角色名图鉴",
        "regex": rf"^(?P<name>{PATTERN})(?:图鉴|wiki|Wiki|WIKI)$",
        "permission": "user",
        "handler": handle_wiki,
    },
]
