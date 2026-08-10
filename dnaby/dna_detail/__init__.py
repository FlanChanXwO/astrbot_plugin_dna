from astrbot.api import logger

from ..dna_config.dna_config import DNAConfig
from ..utils.constants.constants import PATTERN
from ..utils.original_image import get_original_image_path
from ..utils.segments import MessageSegment
from ..utils.session import EventContext, Sender
from .draw_role_card import draw_role_card

ROLE_DETAIL_PATTERN = (
    rf"^(?P<char_name>{PATTERN})(?:面板|信息|详情|面包|🍞)"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_1>{PATTERN}))?"
    rf"(?:\s*[+＋]\s*(?P<weapon_name_2>{PATTERN}))?$"
)


async def handle_role_detail_card(sender: Sender, ctx: EventContext):
    char_name = ctx.regex_dict["char_name"]
    weapon_names = tuple(
        name
        for name in (
            ctx.regex_dict.get("weapon_name_1"),
            ctx.regex_dict.get("weapon_name_2"),
        )
        if name is not None
    )
    logger.info(
        f"[DNA Detail] 触发命令: raw_text={ctx.raw_text}, char_name={char_name}, weapon_names={weapon_names}, at={ctx.at}"
    )
    await draw_role_card(
        sender,
        ctx,
        char_name,
        weapon_names=weapon_names,
    )


async def handle_role_original_image(sender: Sender, ctx: EventContext):
    if not DNAConfig.get_config("RoleOriginalImage").data:
        logger.info("[DNA Detail] 角色原图功能已关闭")
        return

    if ctx.reply is None:
        logger.warning(f"[DNA Detail] 未引用角色面板图: ctx.reply={ctx.reply}")
        return

    image_path = get_original_image_path(ctx.reply)
    if image_path is None:
        logger.warning(f"[DNA Detail] 未找到对应原图: ctx.reply={ctx.reply}")
        return

    sender.send(MessageSegment.image(str(image_path)))


COMMANDS = [
    {
        "key": "role_detail_card",
        "group": "角色信息",
        "name": "角色详情卡片",
        "desc": "查询角色面板/伤害详情",
        "eg": "角色名面板",
        "regex": ROLE_DETAIL_PATTERN,
        "permission": "user",
        "handler": handle_role_detail_card,
    },
    {
        "key": "role_original_image",
        "group": "角色信息",
        "name": "角色原图",
        "desc": "获取所引用面板图的原图",
        "eg": "原图",
        "regex": r"^原图$",
        "permission": "user",
        "handler": handle_role_original_image,
    },
]
