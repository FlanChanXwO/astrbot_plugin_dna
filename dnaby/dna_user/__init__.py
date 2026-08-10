import re

from ..dna_config.dna_config import DNAConfig
from ..utils.database.models import DNABind, DNAUser
from ..utils.msgs.notify import (
    dna_bind_uid_result,
    dna_login_fail,
    send_dna_notify,
    send_dna_text,
)
from ..utils.session import EventContext, Sender
from ..utils.utils import is_uid_hidden
from .login_router import get_cookie, page_login, token_login


async def handle_login(sender: Sender, ctx: EventContext):
    text = re.sub(r'["\n\t ]+', "", ctx.text.strip())
    text = text.replace("，", ",")

    if text == "":
        return await page_login(sender, ctx)

    if "," not in text and len(text) >= 40:
        return await token_login(sender, ctx, text)

    return await dna_login_fail(sender, ctx)


async def handle_logout(sender: Sender, ctx: EventContext):
    uid = await DNABind.get_uid_by_game(ctx.user_id, ctx.bot_id)
    if not uid:
        await send_dna_notify(sender, ctx, "当前并未登录")
        return

    dna_user = await DNAUser.select_dna_user(
        uid,
        ctx.user_id,
        ctx.bot_id,
    )
    if not dna_user:
        await send_dna_notify(sender, ctx, "当前并未登录")
        return

    await DNABind.delete_uid(ctx.user_id, ctx.bot_id, uid)
    await DNAUser.delete_cookie(ctx.user_id, ctx.bot_id, uid)
    await send_dna_notify(sender, ctx, "成功退出登录")


async def handle_bind_uid(sender: Sender, ctx: EventContext):
    arg = ctx.regex_dict.get("arg", "") if ctx.regex_dict else ""
    uid = arg.strip().replace("uid", "").replace("UID", "")
    qid = ctx.user_id
    command = ctx.command or ""

    if "绑定" in command:
        if not uid:
            return await dna_bind_uid_result(sender, ctx, uid, -3)
        uid_list = await DNABind.get_uid_list_by_game(qid, ctx.bot_id)
        cookie_uid_list = await DNAUser.select_user_cookie_uids(qid)
        if uid_list and cookie_uid_list:
            difference_uid_list = set(uid_list).difference(set(cookie_uid_list))
            max_bind_num: int = DNAConfig.get_config("MaxBindNum").data
            if len(difference_uid_list) >= max_bind_num:
                return await dna_bind_uid_result(sender, ctx, uid, -4)

        code = await DNABind.insert_uid(qid, ctx.bot_id, uid, ctx.group_id, lenth_limit=13)
        if code == 0 or code == -2:
            retcode = await DNABind.switch_uid_by_game(qid, ctx.bot_id, uid)
        return await dna_bind_uid_result(sender, ctx, uid, code)
    elif "切换" in command:
        retcode = await DNABind.switch_uid_by_game(qid, ctx.bot_id, uid)
        if retcode == 0:
            uid_list = await DNABind.get_uid_list_by_game(qid, ctx.bot_id)
            if uid_list:
                return await dna_bind_uid_result(sender, ctx, uid_list[0], 1)

        return await dna_bind_uid_result(sender, ctx, uid, -5)
    elif "查看" in command:
        # 检查 UID 是否应该被隐藏（优先群级设置，其次个人设置）
        uid_hidden = await is_uid_hidden(qid, ctx.bot_id, ctx.group_id)

        if uid_hidden:
            return await send_dna_text(sender, ctx, "您已开启UID隐藏，无法查看UID列表~")

        uid_list = await DNABind.get_uid_list_by_game(qid, ctx.bot_id)
        if uid_list:
            uids = "\n".join(uid_list)

            return await dna_bind_uid_result(sender, ctx, uids, 2)
        else:
            return await dna_bind_uid_result(sender, ctx, uid, -5)
    elif "删除全部" in command:
        retcode = await DNABind.delete_all_uid(
            user_id=qid,
            bot_id=ctx.bot_id,
        )
        if retcode == 0:
            return await dna_bind_uid_result(sender, ctx, code=3)
        else:
            return await dna_bind_uid_result(sender, ctx, code=-5)
    else:
        if not uid:
            return await dna_bind_uid_result(sender, ctx, uid, -6)
        data = await DNABind.delete_uid(qid, ctx.bot_id, uid)
        if data == -1:
            return await dna_bind_uid_result(sender, ctx, uid, -6)
        return await dna_bind_uid_result(sender, ctx, uid, 4)


async def handle_get_ck(sender: Sender, ctx: EventContext):
    await send_dna_notify(sender, ctx, await get_cookie(sender, ctx))


COMMANDS = [
    {
        "key": "user_login",
        "group": "皎皎角登录",
        "name": "登录",
        "desc": "皎皎角登录（扫码/网页/短信验证码/token）",
        "eg": "登录",
        # 兼容原有登录别名及常用的 DNA 前缀；前缀只作用于中文登录别名。
        "regex": r"^(?:(?:dna|DNA)?(?:登录|登陆|登入|登龙)|login)\s*(.*)$",
        "permission": "user",
        "handler": handle_login,
    },
    {
        "key": "user_logout",
        "group": "皎皎角登录",
        "name": "退出登录",
        "desc": "退出当前登录",
        "eg": "退出登录",
        "regex": r"^(?:退出登录|登出|logout)$",
        "permission": "user",
        "handler": handle_logout,
    },
    {
        "key": "user_bind",
        "group": "绑定账号",
        "name": "绑定UID",
        "desc": "绑定/切换/删除/查看 UID",
        "eg": "绑定123456",
        "regex": r"^(绑定|切换|删除全部UID|删除全部uid|删除|查看)\s*(?P<arg>\S*)$",
        "permission": "user",
        "handler": handle_bind_uid,
    },
    {
        "key": "user_get_ck",
        "group": "绑定账号",
        "name": "获取ck",
        "desc": "获取当前绑定账号的登录凭据",
        "eg": "获取ck",
        "regex": r"^(?:获取ck|获取CK|获取Token|获取token|获取TOKEN)$",
        "permission": "user",
        "handler": handle_get_ck,
    },
]
