"""账号用例的用户可见文案兼容层。"""

from __future__ import annotations

from collections.abc import Iterable

from ...infrastructure.i18n import get_tip
from .contracts import RoleInfo, TransportErrorKind

ACCOUNT_CONTEXT_UNAVAILABLE = get_tip("account.context_unavailable")
ACCOUNT_SERVICE_UNAVAILABLE = get_tip("account.service_unavailable")
INVALID_LOGIN_INPUT = get_tip("account.invalid_login_input")
LOGIN_CANCELLED = get_tip("account.login_cancelled")
LOGIN_FAILED = get_tip("account.login_failed")
LOGIN_EMPTY_URL = get_tip("account.login_empty_url")
LOGIN_SERVICE_FAILED = get_tip("account.login_service_failed")
LOGIN_EXPIRED = get_tip("account.login_expired")
LOGIN_INVALID_ROLE = get_tip("account.login_invalid_role")
LOGIN_NO_ROLE = get_tip("account.login_no_role")
LOGIN_BIND_LIMIT = get_tip("account.login_bind_limit")
UID_FORMAT_ERROR = get_tip("account.uid_format_error")
UID_BIND_DUPLICATE = get_tip("account.uid_bind_duplicate")
UID_BIND_LIMIT = get_tip("account.uid_bind_limit")
UID_BIND_SUCCESS = get_tip("account.uid_bind_success")
UID_NOT_BOUND = get_tip("account.uid_not_bound")
UID_SWITCH_SUCCESS = get_tip("account.uid_switch_success")
UID_DELETE_SUCCESS = get_tip("account.uid_delete_success")
UID_EMPTY = get_tip("account.uid_empty")
UID_DELETE_ALL_SUCCESS = get_tip("account.uid_delete_all_success")
NOT_LOGGED_IN = get_tip("account.not_logged_in")
LOGOUT_SUCCESS = get_tip("account.logout_success")
CREDENTIALS_EMPTY = get_tip("account.credentials_empty")
LEGACY_COMPLETE_ERROR = get_tip("account.legacy_complete_error")
LEGACY_ROLE_ERROR = get_tip("account.legacy_role_error")
LOGIN_APP_ONLY = get_tip("account.login_app_only")
LOGIN_TOKEN_EMPTY = get_tip("account.login_token_empty")
UNNAMED_ROLE = get_tip("account.unnamed_role")


def login_page(user_id: str, url: str) -> str:
    """返回统一登录提示；地址由 transport 负责生成临时会话。"""

    return get_tip("account.login_page", user_id=user_id, url=url)


def login_success(roles: Iterable[RoleInfo]) -> str:
    """只展示角色标识和名称，不展示 App 凭据。"""

    lines = [get_tip("account.login_success_header")]
    ordered_roles = sorted(roles, key=lambda role: not role.is_default)
    for role in ordered_roles:
        name = role.name or get_tip("account.unnamed_role")
        lines.append(get_tip("account.login_role_line", name=name, uid=role.uid))
    return "\n".join(lines)


def legacy_login_success(role_names: Iterable[str]) -> str:
    lines = [get_tip("account.legacy_login_success_header")]
    lines.extend(
        get_tip("account.legacy_login_role_line", name=name) for name in role_names
    )
    return "\n".join(lines)


def credential_status(available: bool) -> str:
    """把 App 凭据存在性转换为稳定状态文案。"""

    return get_tip(
        "account.credential_status", status="已保存" if available else "未保存"
    )


def transport_error(kind: TransportErrorKind) -> str:
    """将网络边界的内部失败类别映射为安全用户文案。"""

    if kind is TransportErrorKind.NETWORK:
        return get_tip("account.transport_network")
    if kind is TransportErrorKind.STATUS:
        return get_tip("account.transport_status")
    if kind is TransportErrorKind.SERVER:
        return get_tip("account.transport_server")
    if kind is TransportErrorKind.CREDENTIAL:
        return get_tip("common.login_expired")
    return get_tip("account.login_failed")


def binding_list(bindings: Iterable[tuple[str, bool]]) -> str:
    """渲染 UID 列表；调用方在隐私模块接管前显式传入展示值。"""

    lines = [get_tip("account.binding_list_header")]
    lines.extend(
        get_tip(
            "account.binding_list_item",
            uid=uid,
            suffix="（当前）" if is_active else "",
        )
        for uid, is_active in bindings
    )
    return "\n".join(lines)


def credential_summary(records: Iterable[tuple[str, bool]]) -> str:
    """渲染 App 凭据状态，不接收原始 token/cookie。"""

    lines: list[str] = []
    for uid, has_app in records:
        lines.append(get_tip("account.credential_summary_uid", uid=uid))
        lines.append(credential_status(has_app))
    return "\n".join(lines)


__all__ = [
    "ACCOUNT_CONTEXT_UNAVAILABLE",
    "ACCOUNT_SERVICE_UNAVAILABLE",
    "CREDENTIALS_EMPTY",
    "INVALID_LOGIN_INPUT",
    "LEGACY_COMPLETE_ERROR",
    "LEGACY_ROLE_ERROR",
    "LOGIN_APP_ONLY",
    "LOGIN_TOKEN_EMPTY",
    "LOGIN_BIND_LIMIT",
    "LOGIN_CANCELLED",
    "LOGIN_EMPTY_URL",
    "LOGIN_EXPIRED",
    "LOGIN_FAILED",
    "LOGIN_INVALID_ROLE",
    "LOGIN_NO_ROLE",
    "LOGIN_SERVICE_FAILED",
    "LOGOUT_SUCCESS",
    "NOT_LOGGED_IN",
    "UID_BIND_DUPLICATE",
    "UID_BIND_LIMIT",
    "UID_BIND_SUCCESS",
    "UID_DELETE_ALL_SUCCESS",
    "UID_DELETE_SUCCESS",
    "UID_EMPTY",
    "UID_FORMAT_ERROR",
    "UID_NOT_BOUND",
    "UID_SWITCH_SUCCESS",
    "UNNAMED_ROLE",
    "binding_list",
    "credential_status",
    "credential_summary",
    "login_page",
    "legacy_login_success",
    "login_success",
    "transport_error",
]
