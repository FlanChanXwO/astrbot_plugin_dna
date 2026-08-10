"""命令注册表与分发（正则触发）。

- ``ALL_COMMANDS``：聚合各 ``dna_*`` 模块导出的 ``COMMANDS``。
- ``MASTER_PATTERN``：所有命令正则的并集，供 ``@filter.regex`` 门使用。
- ``build_context`` / ``dispatch``：AstrMessageEvent → EventContext，匹配分发。
"""

from __future__ import annotations

import re

from astrbot.api import message_components as Comp
from astrbot.api.event import AstrMessageEvent

from .dna_alias import COMMANDS as _CMD_ALIAS
from .dna_ann import COMMANDS as _CMD_ANN
from .dna_calendar import COMMANDS as _CMD_CALENDAR
from .dna_code import COMMANDS as _CMD_CODE
from .dna_detail import COMMANDS as _CMD_DETAIL
from .dna_guide import COMMANDS as _CMD_GUIDE
from .dna_help import COMMANDS as _CMD_HELP
from .dna_mh import COMMANDS as _CMD_MH
from .dna_privacy import COMMANDS as _CMD_PRIVACY
from .dna_resource import COMMANDS as _CMD_RESOURCE

# 各模块命令注册（模块完成移植后逐个接入）
from .dna_role import COMMANDS as _CMD_ROLE
from .dna_sign import COMMANDS as _CMD_SIGN
from .dna_stamina import COMMANDS as _CMD_STAMINA
from .dna_update import COMMANDS as _CMD_UPDATE
from .dna_upload import COMMANDS as _CMD_UPLOAD
from .dna_user import COMMANDS as _CMD_USER
from .dna_weekly_report import COMMANDS as _CMD_WEEKLY
from .dna_wiki import COMMANDS as _CMD_WIKI
from .utils.msgs.notify import send_dna_text
from .utils.session import EventContext, Sender

ALL_COMMANDS: list[dict] = [
    *_CMD_ROLE,
    *_CMD_SIGN,
    *_CMD_MH,
    *_CMD_ANN,
    *_CMD_CALENDAR,
    *_CMD_CODE,
    *_CMD_DETAIL,
    *_CMD_GUIDE,
    *_CMD_HELP,
    *_CMD_PRIVACY,
    *_CMD_RESOURCE,
    *_CMD_STAMINA,
    *_CMD_UPDATE,
    *_CMD_UPLOAD,
    # 别名删除命令以“删除”开头，必须排在通用 UID 删除命令之前。
    *_CMD_ALIAS,
    *_CMD_USER,
    *_CMD_WEEKLY,
    *_CMD_WIKI,
]

_NAMED_GROUP_PATTERN = re.compile(r"\(\?P<[^>]+>")


def _gate_regex(regex: str) -> str:
    """为 AstrBot 主门移除命名组；具体命令匹配时会重新解析命名组。"""
    return _NAMED_GROUP_PATTERN.sub("(?:", regex)


MASTER_PATTERN = "|".join(f"(?:{_gate_regex(c['regex'])})" for c in ALL_COMMANDS)


def _is_group_admin(event: AstrMessageEvent) -> bool:
    msg_obj = getattr(event, "message_obj", None)
    group = getattr(msg_obj, "group", None)
    if group is None:
        return False
    sender_id = str(event.get_sender_id())
    owners = [str(x) for x in ([group.group_owner] if group.group_owner else [])]
    admins = [str(x) for x in (group.group_admins or [])]
    return sender_id in owners or sender_id in admins


def _check_permission(event: AstrMessageEvent, perm: str, ctx: EventContext) -> bool:
    if perm == "owner":
        if event.is_admin():
            ctx.user_pm = 0
            return True
        ctx.user_pm = 6
        return False
    if perm == "admin":
        if event.is_admin():
            ctx.user_pm = 0
            return True
        if _is_group_admin(event):
            ctx.user_pm = 3
            return True
        ctx.user_pm = 6
        return False
    ctx.user_pm = 6
    return True


def build_context(event: AstrMessageEvent) -> EventContext:
    """从 AstrMessageEvent 构建业务侧只读 EventContext。"""
    group_id = event.get_group_id() or ""
    msgs = list(event.get_messages() or [])
    at = ""
    reply = ""
    image_list: list = []
    for comp in msgs:
        if isinstance(comp, Comp.At):
            qq = str(getattr(comp, "qq", "") or "")
            if qq and qq != "all":
                at = qq
        elif isinstance(comp, Comp.Reply):
            reply = str(getattr(comp, "id", "") or "")
        elif isinstance(comp, Comp.Image):
            image_list.append(comp)
    msg_obj = getattr(event, "message_obj", None)
    raw_text = str(getattr(msg_obj, "message_str", "") or event.message_str or "")
    platform = event.get_platform_name() or ""
    user_type = "group" if group_id else "direct"
    return EventContext(
        message_str=event.message_str or "",
        user_id=event.get_sender_id(),
        bot_id=platform,
        group_id=group_id,
        at=at,
        raw_text=raw_text,
        image_list=image_list,
        reply=reply,
        user_type=user_type,
        unified_msg_origin=str(event.unified_msg_origin or ""),
        platform=platform,
        msg=msgs,
    )


def _extract_text(match: re.Match[str]) -> str:
    gd = match.groupdict()
    if gd.get("arg"):
        return gd["arg"].strip()
    values = [v for v in gd.values() if v]
    if values:
        return values[0].strip()
    if match.lastindex:
        return (match.group(1) or "").strip()
    return ""


async def dispatch(event: AstrMessageEvent, sender: Sender, ctx: EventContext) -> bool:
    """按序匹配命令并执行；命中返回 True。"""
    message = ctx.message_str.strip()
    for cmd in ALL_COMMANDS:
        m = re.match(cmd["regex"], message)
        if not m:
            continue
        if not _check_permission(event, cmd.get("permission", "user"), ctx):
            await send_dna_text(sender, ctx, "权限不足，该命令仅限管理员使用")
            return True
        ctx.command = m.group(0)
        ctx.text = _extract_text(m)
        ctx.regex_dict = m.groupdict()
        ctx.regex_group = tuple(m.groups())
        try:
            await cmd["handler"](sender, ctx)
        except Exception as e:  # noqa: BLE001
            from astrbot.api import logger

            logger.exception(f"[dnaby] 命令 {cmd['key']} 处理异常: {e}")
            await send_dna_text(sender, ctx, "命令执行出错，请查看日志")
        return True
    return False
