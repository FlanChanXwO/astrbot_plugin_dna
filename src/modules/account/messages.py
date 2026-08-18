"""账号用例的用户可见文案。

账号 handler 和 service 不直接散落字符串；集中放置便于审查敏感信息边界，
也让后续隐私模块可以复用同一层的响应约定。
"""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import LoginChannel, RoleInfo, TransportErrorKind

ACCOUNT_CONTEXT_UNAVAILABLE = "无法识别当前用户，暂不能执行账号操作！"
ACCOUNT_SERVICE_UNAVAILABLE = "账号服务尚未初始化，请稍后再试！"
INVALID_LOGIN_INPUT = "登录参数格式错误！"
LOGIN_CANCELLED = "登录已取消"
LOGIN_FAILED = "登录失败！"
LOGIN_EMPTY_URL = "登录失败：登录地址为空！"
LOGIN_INVALID_ROLE = "登录失败：角色数据无效！"
LOGIN_NO_ROLE = "登录失败：未找到可用角色！"
LOGIN_BIND_LIMIT = "登录失败：UID绑定数量已达上限！"
UID_FORMAT_ERROR = "UID格式错误！"
UID_BIND_DUPLICATE = "该UID已经绑定过了！"
UID_BIND_LIMIT = "UID绑定数量已达上限！"
UID_BIND_SUCCESS = "UID绑定成功！"
UID_NOT_BOUND = "该UID尚未绑定！"
UID_SWITCH_SUCCESS = "UID切换成功！"
UID_DELETE_SUCCESS = "UID删除成功！"
UID_EMPTY = "当前没有已绑定的UID！"
UID_DELETE_ALL_SUCCESS = "已删除全部UID！"
NOT_LOGGED_IN = "当前并未登录"
LOGOUT_SUCCESS = "成功退出登录"
CREDENTIALS_EMPTY = "当前没有已保存的登录凭据！"


def login_page(url: str) -> str:
    """返回登录页地址；地址由 transport 负责生成临时会话。"""

    return f"登录地址：{url}"


def login_success(roles: Iterable[RoleInfo], channel: LoginChannel) -> str:
    """只展示角色标识和名称，不展示 transport 凭据。"""

    lines = ["登录成功，已为您绑定以下角色："]
    # legacy 将默认角色放在成功文案最前面；排序保持同一优先级下的 transport 顺序。
    ordered_roles = sorted(roles, key=lambda role: not role.is_default)
    for role in ordered_roles:
        name = role.name or "未命名角色"
        lines.append(f"- 名字：{name}，UID：{role.uid}")
    if channel is LoginChannel.WEB:
        lines.append("Web 登录暂不支持签到、体力和周报")
    return "\n".join(lines)


def credential_status(channel: LoginChannel, available: bool) -> str:
    """把凭据存在性转换为稳定状态文案。"""

    label = "App" if channel is LoginChannel.APP else "Web"
    return f"{label} 凭据：{'已保存' if available else '未保存'}"


def transport_error(kind: TransportErrorKind) -> str:
    """将网络边界的内部失败类别映射为安全用户文案。"""

    if kind is TransportErrorKind.NETWORK:
        return "登录失败：网络错误！"
    if kind is TransportErrorKind.STATUS:
        return "登录失败：状态错误！"
    if kind is TransportErrorKind.SERVER:
        return "登录失败：服务端错误！"
    return LOGIN_FAILED


def binding_list(bindings: Iterable[tuple[str, bool]]) -> str:
    """渲染 UID 列表；调用方在隐私模块接管前显式传入展示值。"""

    lines = ["已绑定UID："]
    lines.extend(
        f"- {uid}{'（当前）' if is_active else ''}"
        for uid, is_active in bindings
    )
    return "\n".join(lines)


def credential_summary(
    records: Iterable[tuple[str, bool, bool]],
) -> str:
    """渲染凭据状态三元组，不接收原始 token/cookie。"""

    lines: list[str] = []
    for uid, has_app, has_web in records:
        lines.append(f"UID：{uid}")
        lines.append(credential_status(LoginChannel.APP, has_app))
        lines.append(credential_status(LoginChannel.WEB, has_web))
    return "\n".join(lines)


__all__ = [
    "ACCOUNT_CONTEXT_UNAVAILABLE",
    "ACCOUNT_SERVICE_UNAVAILABLE",
    "CREDENTIALS_EMPTY",
    "INVALID_LOGIN_INPUT",
    "LOGIN_BIND_LIMIT",
    "LOGIN_CANCELLED",
    "LOGIN_EMPTY_URL",
    "LOGIN_FAILED",
    "LOGIN_INVALID_ROLE",
    "LOGIN_NO_ROLE",
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
    "binding_list",
    "credential_status",
    "credential_summary",
    "login_page",
    "login_success",
    "transport_error",
]
