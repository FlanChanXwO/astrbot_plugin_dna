from ..utils.constants.constants import PATTERN
from ..utils.session import EventContext, Sender
from .guide import get_guide


async def handle_role_guide(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict.get("char_name", "")
    await get_guide(sender, ctx, char_name)


COMMANDS = [
    {
        "key": "dna_guide",
        "group": "攻略",
        "name": "角色攻略",
        "desc": "查看角色攻略图",
        "eg": "角色名攻略",
        "regex": rf"^(?P<char_name>{PATTERN})攻略$",
        "permission": "user",
        "handler": handle_role_guide,
    },
]
