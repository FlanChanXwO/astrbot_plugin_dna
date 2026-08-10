from ..utils.constants.constants import PATTERN
from ..utils.msgs.notify import send_dna_text
from ..utils.name_convert import load_alias_data, refresh_name_convert
from ..utils.session import EventContext, Sender
from .alias_ops import (
    action_char_alias,
    action_weapon_alias,
    all_char_list_alias,
    all_weapon_list_alias,
    char_alias_list,
    weapon_alias_list,
)


async def handle_add_alias(sender: Sender, ctx: EventContext):
    action = ctx.regex_dict.get("action", "")
    alias_type = ctx.regex_dict.get("alias_type")
    is_weapon = alias_type == "武器"
    name = ctx.regex_dict.get("name", "").strip()
    new_alias = ctx.regex_dict.get("new_alias", "").strip()
    if not name or not new_alias:
        return await send_dna_text(sender, ctx, "名称或别名不能为空")

    if is_weapon:
        msg = await action_weapon_alias(action, name, new_alias)
    else:
        msg = await action_char_alias(action, name, new_alias)

    if "成功" in msg:
        load_alias_data()
    await send_dna_text(sender, ctx, msg)


async def handle_list_alias(sender: Sender, ctx: EventContext):
    alias_type = ctx.regex_dict.get("alias_type")
    is_weapon = alias_type == "武器"
    name = ctx.regex_dict.get("name")
    if not name:
        return await send_dna_text(sender, ctx, "名称不能为空")
    name = name.strip()

    if is_weapon:
        msg = await weapon_alias_list(name)
    else:
        msg = await char_alias_list(name)
    await send_dna_text(sender, ctx, msg)


async def handle_recover_alias(sender: Sender, ctx: EventContext):
    is_force = "强制" in ctx.command
    _, msg = await refresh_name_convert(is_force=is_force)
    await send_dna_text(sender, ctx, msg)


async def handle_all_list_alias(sender: Sender, ctx: EventContext):
    alias_type = ctx.command
    if alias_type == "角色列表":
        msg = await all_char_list_alias()
    else:
        msg = await all_weapon_list_alias()
    await send_dna_text(sender, ctx, msg)


COMMANDS = [
    {
        "key": "alias_add_delete",
        "group": "bot主人功能",
        "name": "添加/删除别名",
        "desc": "添加或删除角色/武器别名",
        "eg": "添加角色辛西娅别名小辛",
        "regex": rf"^(?P<action>添加|删除)(?P<alias_type>角色|武器)?(?P<name>{PATTERN})别名(?P<new_alias>{PATTERN})$",
        "permission": "owner",
        "handler": handle_add_alias,
    },
    {
        "key": "alias_list",
        "group": "bot主人功能",
        "name": "别名列表",
        "desc": "查看角色/武器别名列表",
        "eg": "辛西娅别名",
        "regex": rf"^(?P<alias_type>角色|武器)?(?P<name>{PATTERN})别名(列表)?$",
        "permission": "owner",
        "handler": handle_list_alias,
    },
    {
        "key": "alias_recover",
        "group": "bot主人功能",
        "name": "恢复别名",
        "desc": "恢复/强制恢复内置别名",
        "eg": "恢复别名",
        "regex": r"^(?:恢复别名|强制恢复别名)$",
        "permission": "owner",
        "handler": handle_recover_alias,
    },
    {
        "key": "alias_all_list",
        "group": "bot主人功能",
        "name": "角色/武器列表",
        "desc": "查看全部角色或武器列表",
        "eg": "角色列表",
        "regex": r"^(?:角色列表|武器列表)$",
        "permission": "user",
        "handler": handle_all_list_alias,
    },
]
