"""资料查询的用户可见文案兼容层。"""

from datetime import datetime

from ...infrastructure.i18n import get_tip
from .contracts import CodeEntry

CONTEXT_UNAVAILABLE = get_tip("encyclopedia.context_unavailable")
SERVICE_UNAVAILABLE = get_tip("encyclopedia.service_unavailable")
UID_INVALID = get_tip("encyclopedia.uid_invalid")
PEEK_BLOCKED = get_tip("encyclopedia.peek_blocked")
CODE_TITLE = get_tip("encyclopedia.code_title")
CODE_EMPTY = get_tip("encyclopedia.code_empty")


def account_not_bound(*, target: bool = False) -> str:
    """生成本地账号绑定缺失文案。"""

    return get_tip(
        "common.target_account_not_bound" if target else "common.account_not_bound"
    )


def transport_error(kind: str, *, target: bool = False) -> str:
    """按安全失败类别生成稳定文案。"""

    if kind == "credential":
        return get_tip(
            "common.credential_invalid" if target else "common.login_expired"
        )
    return get_tip("common.service_unavailable")


def not_found(resource: str) -> str:
    """生成资源未找到文案，不包含底层路径。"""

    return get_tip("encyclopedia.not_found", resource=resource)


def code_expiry(value: str) -> str:
    return get_tip("encyclopedia.code_expires_at", value=value)


def weekly_type_invalid() -> str:
    return get_tip("encyclopedia.weekly_type_invalid")


def guide_author(provider: str) -> str:
    return get_tip("encyclopedia.guide_author", provider=provider)


def alias_weapon_not_found(name: str) -> str:
    return get_tip("encyclopedia.alias_weapon_not_found", name=name)


def alias_weapon_list(name: str, aliases: str) -> str:
    return get_tip("encyclopedia.alias_weapon_list", name=name, aliases=aliases)


def alias_char_not_found(name: str) -> str:
    return get_tip("encyclopedia.alias_char_not_found", name=name)


def alias_char_list(name: str, aliases: str) -> str:
    return get_tip("encyclopedia.alias_char_list", name=name, aliases=aliases)


def alias_all_list(kind: str, items: str) -> str:
    key = "encyclopedia.weapon_list" if kind == "武器" else "encyclopedia.char_list"
    return get_tip(key, items=items)


def _format_code_datetime(value: datetime) -> str:
    """按兑换码展示约定格式化已由 transport 规范化的时间。"""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def code_entry(entry: CodeEntry | str, expiry: str = "") -> str:
    """渲染兑换码本身及 provider 提供的非空可选字段。"""

    if isinstance(entry, str):
        return (
            get_tip("encyclopedia.code_expiry_only", code=entry, expiry=expiry)
            if expiry
            else entry
        )

    if (
        entry.expires_at is not None
        and not entry.reward
        and entry.valid_from is None
        and not entry.platforms
        and not entry.servers
    ):
        return get_tip(
            "encyclopedia.code_expiry_only",
            code=entry.code,
            expiry=_format_code_datetime(entry.expires_at),
        )

    lines = [entry.code]
    if entry.reward:
        lines.append(get_tip("encyclopedia.code_reward", reward=entry.reward))
    if entry.valid_from is not None:
        lines.append(
            get_tip(
                "encyclopedia.code_valid_from",
                value=_format_code_datetime(entry.valid_from),
            )
        )
    if entry.expires_at is not None:
        lines.append(
            get_tip(
                "encyclopedia.code_expires_at",
                value=_format_code_datetime(entry.expires_at),
            )
        )
    if entry.platforms:
        lines.append(
            get_tip("encyclopedia.code_platforms", value="、".join(entry.platforms))
        )
    if entry.servers:
        lines.append(
            get_tip("encyclopedia.code_servers", value="、".join(entry.servers))
        )
    return "\n".join(lines)


__all__ = [
    "CODE_EMPTY",
    "CODE_TITLE",
    "CONTEXT_UNAVAILABLE",
    "PEEK_BLOCKED",
    "SERVICE_UNAVAILABLE",
    "UID_INVALID",
    "account_not_bound",
    "alias_all_list",
    "alias_char_list",
    "alias_char_not_found",
    "alias_weapon_list",
    "alias_weapon_not_found",
    "code_entry",
    "code_expiry",
    "guide_author",
    "not_found",
    "transport_error",
    "weekly_type_invalid",
]
