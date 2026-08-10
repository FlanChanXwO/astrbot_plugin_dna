from ..utils.session import EventContext, Sender
from .code import get_dna_code_info


async def handle_dna_code(sender: Sender, ctx: EventContext):
    await get_dna_code_info(sender, ctx)


COMMANDS = [
    {
        "key": "dna_code",
        "group": "兑换码",
        "name": "兑换码",
        "desc": "查看当前可用的兑换码",
        "eg": "兑换码",
        "regex": r"^(?:兑换码|cdk|CDK|code)$",
        "permission": "user",
        "handler": handle_dna_code,
    },
]
