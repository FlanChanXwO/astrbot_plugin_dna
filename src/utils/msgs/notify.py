from ...utils.utils import get_using_id, is_uid_hidden, mask_uid_in_text
from ..session import EventContext, Sender

title = "[二重螺旋]\n"
HTML_RENDER_FAILED = "图片渲染失败，请稍后重试；管理员可查看日志了解详情。"
MENTION_TARGET_UNRESOLVED = "未识别到有效的 @ 目标，请重新@要查询的用户后再试。"


async def send_dna_notify(
    sender: Sender,
    ctx: EventContext,
    msg: str,
    need_at: bool = True,
    is_uid_list_view: bool = False,
    prefix: str = title,
    immediate: bool = False,
):
    """发送DNA通知消息

    Args:
        sender: 发送器
        ctx: 事件上下文
        msg: 消息内容
        need_at: 是否需要@发送者
        is_uid_list_view: 是否为查看UID列表的请求（此时不脱敏）
    """
    # 检查是否需要脱敏（除非是查看UID列表）
    if not is_uid_list_view and ctx.group_id:
        uid_hidden = await is_uid_hidden(ctx.user_id, ctx.bot_id, ctx.group_id)
        if uid_hidden:
            msg = _mask_uid_in_message(msg)
    elif not is_uid_list_view:
        # 私聊场景
        uid_hidden = await is_uid_hidden(ctx.user_id, ctx.bot_id)
        if uid_hidden:
            msg = _mask_uid_in_message(msg)

    if need_at:
        at_sender = bool(ctx.group_id)
    else:
        at_sender = False
    if immediate:
        await sender.send_now(f"{prefix}{msg}", at_sender=at_sender)
    else:
        sender.send(f"{prefix}{msg}", at_sender=at_sender)


async def send_dna_text(
    sender: Sender,
    ctx: EventContext,
    msg: str,
    need_at: bool = False,
    immediate: bool = False,
):
    """发送历史纯文本消息，统一经过 UID 脱敏与 Sender 适配。"""
    return await send_dna_notify(
        sender,
        ctx,
        msg,
        need_at=need_at,
        prefix="",
        immediate=immediate,
    )


def _mask_uid_in_message(msg: str) -> str:
    """对消息中的UID进行脱敏处理"""
    return mask_uid_in_text(msg)


async def dna_uid_invalid(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    is_use_other_id = await get_using_id(ctx) != ctx.user_id
    msg = (
        [
            "登录已失效，请重新登录",
            f"请重新输入命令【{DNA_PREFIX}登录】进行登录",
        ]
        if not is_use_other_id
        else ["该用户尚未登录", f"请让该用户输入命令【{DNA_PREFIX}登录】进行登录"]
    )
    msg = "\n".join(msg)
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_token_invalid(sender: Sender, ctx: EventContext, need_at: bool = True):
    msg = ["Token无效，请重新登录"]
    is_use_other_id = await get_using_id(ctx) != ctx.user_id
    msg = "\n".join(msg) if not is_use_other_id else "该用户的 Token 无效"
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_not_found(
    sender: Sender, ctx: EventContext, resource_name: str, need_at: bool = True
):
    return await send_dna_notify(
        sender, ctx, f"{resource_name}未找到，请检查是否正确", need_at
    )


async def dna_peek_blocked(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNAConfig

    allow_config = DNAConfig.get_config("AllowAtQuery")
    if not allow_config or not allow_config.data:
        msg = "AT查询功能未开启，无法查看他人游戏信息"
    else:
        msg = "该用户开启了防偷窥，无法查看其游戏信息"
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_not_unlocked(
    sender: Sender, ctx: EventContext, resource_name: str, need_at: bool = True
):
    return await send_dna_notify(
        sender, ctx, f"{resource_name}暂未拥有，无法查看", need_at
    )


async def dna_login_fail(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    msg = [
        "账号登录失败",
        f"请重新输入命令【{DNA_PREFIX}登录】进行登录",
    ]
    msg = "\n".join(msg)
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_login_timeout(sender: Sender, ctx: EventContext, need_at: bool = True):
    msg = [
        "登录超时, 请重新登录",
    ]
    msg = "\n".join(msg)
    return await send_dna_notify(sender, ctx, msg)


async def dna_code_login_fail(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    msg = [
        "手机号+验证码登录失败",
        f"请重新输入命令【{DNA_PREFIX}登录 手机号,验证码】进行登录",
    ]
    msg = "\n".join(msg)
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_login_success(sender: Sender, ctx: EventContext, need_at: bool = True):
    msg = [
        "登录成功",
    ]
    msg = "\n".join(msg)
    return await send_dna_notify(sender, ctx, msg, need_at)


async def dna_bind_uid_result(
    sender: Sender,
    ctx: EventContext,
    uid: str = "",
    code: int = 0,
    need_at: bool = True,
):
    from ...infrastructure.config.settings import DNA_PREFIX

    code_map = {
        4: [
            "UID删除成功！",
        ],
        3: [
            "删除全部UID成功！",
        ],
        2: [
            f"绑定的UID列表为：\n{uid}",
        ],
        1: [
            "UID切换成功！",
        ],
        0: [
            "UID绑定成功！",
            f"当前仅支持查询部分信息，完整功能请使用【{DNA_PREFIX}登录】",
        ],
        -1: [
            "UID的位数不正确！",
            f"请重新输入命令【{DNA_PREFIX}绑定 UID】进行绑定",
        ],
        -2: [
            "该UID已经绑定过了！",
            f"请重新输入命令【{DNA_PREFIX}绑定 UID】进行绑定",
        ],
        -3: [
            "你输入了错误的格式!",
            f"请重新输入命令【{DNA_PREFIX}绑定 UID】进行绑定",
        ],
        -4: [
            "绑定UID达到上限!",
        ],
        -5: [
            "尚未绑定任何UID!",
        ],
        -6: [
            "删除失败！",
            "该命令末尾需要跟正确的UID!",
            "例如【{DNA_PREFIX}删除123456】",
        ],
        -99: [
            "绑定失败",
            f"请重新输入命令【{DNA_PREFIX}绑定 UID】进行绑定",
        ],
    }
    if code not in code_map:
        raise ValueError(f"Invalid code: {code}")

    # 查看UID列表时不脱敏（code=2）
    is_uid_list_view = code == 2
    return await send_dna_notify(
        sender,
        ctx,
        "\n".join(code_map[code]),
        need_at=need_at,
        is_uid_list_view=is_uid_list_view,
    )
