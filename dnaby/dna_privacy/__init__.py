from ..utils.session import EventContext, Sender
from .privacy import (
    cancel_peek_all,
    cancel_uid_hidden_all,
    disable_peek_admin,
    disable_peek_all,
    disable_peek_personal,
    disable_uid_hidden,
    disable_uid_hidden_admin,
    disable_uid_hidden_all,
    enable_peek_admin,
    enable_peek_all,
    enable_peek_personal,
    enable_uid_hidden,
    enable_uid_hidden_admin,
    enable_uid_hidden_all,
)

# ==================== 个人隐私控制（user） ====================


async def handle_enable_peek_personal(sender: Sender, ctx: EventContext):
    await enable_peek_personal(sender, ctx)


async def handle_disable_peek_personal(sender: Sender, ctx: EventContext):
    await disable_peek_personal(sender, ctx)


async def handle_enable_uid_hidden(sender: Sender, ctx: EventContext):
    await enable_uid_hidden(sender, ctx)


async def handle_disable_uid_hidden(sender: Sender, ctx: EventContext):
    await disable_uid_hidden(sender, ctx)


# ==================== 群管理员隐私控制（admin） ====================


async def handle_enable_peek_admin(sender: Sender, ctx: EventContext):
    await enable_peek_admin(sender, ctx)


async def handle_disable_peek_admin(sender: Sender, ctx: EventContext):
    await disable_peek_admin(sender, ctx)


async def handle_enable_peek_all(sender: Sender, ctx: EventContext):
    await enable_peek_all(sender, ctx)


async def handle_disable_peek_all(sender: Sender, ctx: EventContext):
    await disable_peek_all(sender, ctx)


async def handle_cancel_peek_all(sender: Sender, ctx: EventContext):
    await cancel_peek_all(sender, ctx)


async def handle_enable_uid_hidden_admin(sender: Sender, ctx: EventContext):
    await enable_uid_hidden_admin(sender, ctx)


async def handle_disable_uid_hidden_admin(sender: Sender, ctx: EventContext):
    await disable_uid_hidden_admin(sender, ctx)


async def handle_enable_uid_hidden_all(sender: Sender, ctx: EventContext):
    await enable_uid_hidden_all(sender, ctx)


async def handle_disable_uid_hidden_all(sender: Sender, ctx: EventContext):
    await disable_uid_hidden_all(sender, ctx)


async def handle_cancel_uid_hidden_all(sender: Sender, ctx: EventContext):
    await cancel_uid_hidden_all(sender, ctx)


COMMANDS = [
    # ---- 个人隐私 ----
    {
        "key": "privacy_enable_peek_personal",
        "group": "隐私控制",
        "name": "开偷窥",
        "desc": "允许被其它人查看自己的游戏信息",
        "eg": "开偷窥",
        "regex": r"^(?:开偷窥|关闭偷窥防护)$",
        "permission": "user",
        "handler": handle_enable_peek_personal,
    },
    {
        "key": "privacy_disable_peek_personal",
        "group": "隐私控制",
        "name": "防偷窥",
        "desc": "禁止被其它人查看自己的游戏信息",
        "eg": "防偷窥",
        "regex": r"^(?:防偷窥|开启偷窥防护)$",
        "permission": "user",
        "handler": handle_disable_peek_personal,
    },
    {
        "key": "privacy_enable_uid_hidden",
        "group": "隐私控制",
        "name": "隐藏UID",
        "desc": "在生成的卡片中隐藏自己的UID",
        "eg": "隐藏UID",
        "regex": r"^(?:隐藏UID|隐藏uid)$",
        "permission": "user",
        "handler": handle_enable_uid_hidden,
    },
    {
        "key": "privacy_disable_uid_hidden",
        "group": "隐私控制",
        "name": "显示UID",
        "desc": "在生成的卡片中显示自己的UID",
        "eg": "显示UID",
        "regex": r"^(?:显示UID|显示uid)$",
        "permission": "user",
        "handler": handle_disable_uid_hidden,
    },
    # ---- 群管理员：偷窥 ----
    {
        "key": "privacy_enable_peek_admin",
        "group": "群管理员功能",
        "name": "指定开偷窥",
        "desc": "允许会话中被艾特的玩家被其它人查看该玩家的游戏信息",
        "eg": "指定开偷窥",
        "regex": r"^指定开偷窥$",
        "permission": "admin",
        "handler": handle_enable_peek_admin,
    },
    {
        "key": "privacy_disable_peek_admin",
        "group": "群管理员功能",
        "name": "指定防偷窥",
        "desc": "禁止会话中被艾特的玩家被其它人查看该玩家的游戏信息",
        "eg": "指定防偷窥",
        "regex": r"^指定防偷窥$",
        "permission": "admin",
        "handler": handle_disable_peek_admin,
    },
    {
        "key": "privacy_enable_peek_all",
        "group": "群管理员功能",
        "name": "全体开偷窥",
        "desc": "允许会话中所有玩家相互查看自己的游戏信息",
        "eg": "全体开偷窥",
        "regex": r"^全体开偷窥$",
        "permission": "admin",
        "handler": handle_enable_peek_all,
    },
    {
        "key": "privacy_disable_peek_all",
        "group": "群管理员功能",
        "name": "全体防偷窥",
        "desc": "禁止会话中所有玩家相互查看自己的游戏信息",
        "eg": "全体防偷窥",
        "regex": r"^全体防偷窥$",
        "permission": "admin",
        "handler": handle_disable_peek_all,
    },
    {
        "key": "privacy_cancel_peek_all",
        "group": "群管理员功能",
        "name": "取消全体偷窥",
        "desc": "取消全体偷窥设置，恢复个人设置",
        "eg": "取消全体偷窥",
        "regex": r"^取消全体偷窥$",
        "permission": "admin",
        "handler": handle_cancel_peek_all,
    },
    # ---- 群管理员：UID 隐藏 ----
    {
        "key": "privacy_enable_uid_hidden_admin",
        "group": "群管理员功能",
        "name": "指定隐藏UID",
        "desc": "为会话中被艾特的玩家开启UID隐藏",
        "eg": "指定隐藏UID",
        "regex": r"^指定隐藏UID$",
        "permission": "admin",
        "handler": handle_enable_uid_hidden_admin,
    },
    {
        "key": "privacy_disable_uid_hidden_admin",
        "group": "群管理员功能",
        "name": "指定显示UID",
        "desc": "为会话中被艾特的玩家关闭UID隐藏",
        "eg": "指定显示UID",
        "regex": r"^指定显示UID$",
        "permission": "admin",
        "handler": handle_disable_uid_hidden_admin,
    },
    {
        "key": "privacy_enable_uid_hidden_all",
        "group": "群管理员功能",
        "name": "全体隐藏UID",
        "desc": "强制会话中所有玩家隐藏UID",
        "eg": "全体隐藏UID",
        "regex": r"^全体隐藏UID$",
        "permission": "admin",
        "handler": handle_enable_uid_hidden_all,
    },
    {
        "key": "privacy_disable_uid_hidden_all",
        "group": "群管理员功能",
        "name": "全体显示UID",
        "desc": "强制会话中所有玩家显示UID",
        "eg": "全体显示UID",
        "regex": r"^全体显示UID$",
        "permission": "admin",
        "handler": handle_disable_uid_hidden_all,
    },
    {
        "key": "privacy_cancel_uid_hidden_all",
        "group": "群管理员功能",
        "name": "取消全体UID隐藏",
        "desc": "取消全体UID隐藏设置，恢复个人设置",
        "eg": "取消全体UID隐藏",
        "regex": r"^取消全体UID隐藏$",
        "permission": "admin",
        "handler": handle_cancel_uid_hidden_all,
    },
]
