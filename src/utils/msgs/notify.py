from ...infrastructure.i18n import get_tip
from ...utils.utils import get_using_id, is_uid_hidden, mask_uid_in_text
from ..session import EventContext, Sender

title = get_tip("legacy.title")
HTML_RENDER_FAILED = get_tip("legacy.html_render_failed")
MENTION_TARGET_UNRESOLVED = get_tip("legacy.mention_target_unresolved")


async def send_dna_notify(
    sender: Sender,
    ctx: EventContext,
    msg: str,
    need_at: bool = True,
    is_uid_list_view: bool = False,
    prefix: str = title,
    immediate: bool = False,
):
    """发送 DNA 通知消息，并统一执行 UID 脱敏和 Sender 适配。"""
    if not is_uid_list_view and ctx.group_id:
        uid_hidden = await is_uid_hidden(ctx.user_id, ctx.bot_id, ctx.group_id)
        if uid_hidden:
            msg = _mask_uid_in_message(msg)
    elif not is_uid_list_view:
        uid_hidden = await is_uid_hidden(ctx.user_id, ctx.bot_id)
        if uid_hidden:
            msg = _mask_uid_in_message(msg)

    at_sender = bool(ctx.group_id) if need_at else False
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
    """对消息中的 UID 进行脱敏处理。"""
    return mask_uid_in_text(msg)


async def dna_uid_invalid(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    is_use_other_id = await get_using_id(ctx) != ctx.user_id
    if is_use_other_id:
        msg = [
            get_tip("legacy.uid_invalid_target"),
            get_tip("legacy.target_login_command", prefix=DNA_PREFIX),
        ]
    else:
        msg = [
            get_tip("legacy.uid_invalid_self"),
            get_tip("legacy.login_command", prefix=DNA_PREFIX),
        ]
    return await send_dna_notify(sender, ctx, "\n".join(msg), need_at)


async def dna_token_invalid(sender: Sender, ctx: EventContext, need_at: bool = True):
    is_use_other_id = await get_using_id(ctx) != ctx.user_id
    key = (
        "legacy.token_invalid_target"
        if is_use_other_id
        else "legacy.token_invalid_self"
    )
    return await send_dna_notify(sender, ctx, get_tip(key), need_at)


async def dna_not_found(
    sender: Sender, ctx: EventContext, resource_name: str, need_at: bool = True
):
    return await send_dna_notify(
        sender,
        ctx,
        get_tip("legacy.not_found", resource=resource_name),
        need_at,
    )


async def dna_peek_blocked(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNAConfig

    allow_config = DNAConfig.get_config("AllowAtQuery")
    key = (
        "legacy.peek_disabled"
        if not allow_config or not allow_config.data
        else "legacy.peek_blocked"
    )
    return await send_dna_notify(sender, ctx, get_tip(key), need_at)


async def dna_not_unlocked(
    sender: Sender, ctx: EventContext, resource_name: str, need_at: bool = True
):
    return await send_dna_notify(
        sender,
        ctx,
        get_tip("legacy.not_unlocked", resource=resource_name),
        need_at,
    )


async def dna_login_fail(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    msg = [
        get_tip("legacy.login_fail"),
        get_tip("legacy.login_command", prefix=DNA_PREFIX),
    ]
    return await send_dna_notify(sender, ctx, "\n".join(msg), need_at)


async def dna_login_timeout(sender: Sender, ctx: EventContext, need_at: bool = True):
    return await send_dna_notify(sender, ctx, get_tip("legacy.login_timeout"))


async def dna_code_login_fail(sender: Sender, ctx: EventContext, need_at: bool = True):
    from ...infrastructure.config.settings import DNA_PREFIX

    msg = [
        get_tip("legacy.code_login_fail"),
        get_tip("legacy.code_login_command", prefix=DNA_PREFIX),
    ]
    return await send_dna_notify(sender, ctx, "\n".join(msg), need_at)


async def dna_login_success(sender: Sender, ctx: EventContext, need_at: bool = True):
    return await send_dna_notify(sender, ctx, get_tip("legacy.login_success"), need_at)


async def dna_bind_uid_result(
    sender: Sender,
    ctx: EventContext,
    uid: str = "",
    code: int = 0,
    need_at: bool = True,
):
    from ...infrastructure.config.settings import DNA_PREFIX

    def bind_command() -> str:
        return get_tip("legacy.bind_bind_command", prefix=DNA_PREFIX)

    code_map = {
        4: [get_tip("legacy.bind_delete")],
        3: [get_tip("legacy.bind_delete_all")],
        2: [get_tip("legacy.bind_list", uid=uid)],
        1: [get_tip("legacy.bind_switch")],
        0: [
            get_tip("legacy.bind_success"),
            get_tip("legacy.bind_partial_login", prefix=DNA_PREFIX),
        ],
        -1: [get_tip("legacy.bind_invalid_length"), bind_command()],
        -2: [get_tip("legacy.bind_duplicate"), bind_command()],
        -3: [get_tip("legacy.bind_bad_format"), bind_command()],
        -4: [get_tip("legacy.bind_limit")],
        -5: [get_tip("legacy.bind_none")],
        -6: [
            get_tip("legacy.bind_delete_failed"),
            get_tip("legacy.bind_delete_suffix"),
            get_tip("legacy.bind_delete_example", prefix=DNA_PREFIX),
        ],
        -99: [get_tip("legacy.bind_failed"), bind_command()],
    }
    if code not in code_map:
        raise ValueError(f"Invalid code: {code}")

    return await send_dna_notify(
        sender,
        ctx,
        "\n".join(code_map[code]),
        need_at=need_at,
        is_uid_list_view=code == 2,
    )
