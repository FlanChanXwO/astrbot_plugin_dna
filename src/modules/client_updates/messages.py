"""客户端更新命令、订阅与查询结果的用户可见文案。"""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import ClientPlatform, ClientSourceVersion, ClientUpdateChange
from .registry import resolve_client_update_target

CLIENT_UPDATE_CONTEXT_UNAVAILABLE = "客户端更新查询上下文不可用"
CLIENT_UPDATE_SERVICE_UNAVAILABLE = "客户端更新服务不可用"
CLIENT_UPDATE_ADMIN_ONLY = "仅群管理员可管理客户端更新订阅"
CLIENT_UPDATE_GROUP_ONLY = "请在群聊中订阅客户端更新"
CLIENT_UPDATE_GROUP_UNSUB_ONLY = "请在群聊中取消订阅客户端更新"
CLIENT_UPDATE_UNAVAILABLE = "客户端更新暂时无法获取"

CLIENT_UPDATE_SUBSCRIPTION_TYPE = "订阅DNA客户端更新"
CLIENT_UPDATE_ALREADY_SUBSCRIBED = "已经订阅客户端更新"
CLIENT_UPDATE_SUBSCRIBED = "成功订阅客户端更新！"
CLIENT_UPDATE_SUBSCRIBED_RETRY = (
    "已保存客户端更新订阅，首次检查暂时失败，将在下次检查重试。"
)
CLIENT_UPDATE_UNSUBSCRIBED = "成功取消订阅客户端更新！"
CLIENT_UPDATE_NOT_SUBSCRIBED = "未曾订阅客户端更新！"

_DETECTED_PREFIX = "检测到二重螺旋客户端"

_PLATFORM_NAMES = {
    ClientPlatform.PC: "PC",
    ClientPlatform.ANDROID: "安卓",
    ClientPlatform.IOS: "iOS",
}


def platform_name(platform: ClientPlatform) -> str:
    """返回面向用户的稳定平台名称。"""

    return _PLATFORM_NAMES[ClientPlatform(platform)]


def format_current(
    version: ClientSourceVersion,
    target_names: Sequence[str],
) -> str:
    """格式化没有可比较基线时的 Source 当前版本。"""

    return (
        f"{_DETECTED_PREFIX}\n"
        f"目标：{_format_target_names(target_names)}\n"
        f"当前版本：{_version_text_label(version.version_text)}\n"
        "上次版本：暂无；新增更新：暂无可比较大小"
    )


def format_no_change(
    version: ClientSourceVersion,
    target_names: Sequence[str],
) -> str:
    """格式化已有基线但 Source 版本未变化的查询结果。"""

    return (
        f"{_DETECTED_PREFIX}\n"
        f"目标：{_format_target_names(target_names)}\n"
        f"当前版本：{_version_text_label(version.version_text)}\n"
        "新增更新：暂无"
    )


def format_change(
    change: ClientUpdateChange,
    target_names: Sequence[str] | None = None,
) -> str:
    """格式化一次 Source 变化，并完整列出事件覆盖的 Target。"""

    names = (
        tuple(target_names)
        if target_names is not None
        else tuple(
            resolve_client_update_target(target_id).display_name
            for target_id in change.target_ids
        )
    )
    added_size = (
        format_size(change.added_size_bytes)
        if change.history_complete and change.added_size_bytes is not None
        else "大小未知（历史窗口已变化）"
    )
    return (
        f"{_DETECTED_PREFIX}更新\n"
        f"目标：{_format_target_names(names)}\n"
        f"版本：{_change_version_line(change)}\n"
        f"新增更新：{added_size}"
    )


def _version_text_label(version_text: str | None) -> str:
    """无公开版本号的发行渠道按安装包标识跟踪，不伪造版本号。"""

    if version_text is not None:
        return version_text
    return "暂无公开版本号（按发行包标识跟踪）"


def _change_version_line(change: ClientUpdateChange) -> str:
    previous = change.previous.version_text
    current = change.current.version_text
    if previous is not None and current is not None:
        return f"{previous} → {current}"
    return "发行包已更新（该渠道不提供公开版本号）"


def format_size(size_bytes: int) -> str:
    """把字节数格式化为适合聊天消息的单位。"""

    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.2f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def _format_target_names(target_names: Sequence[str]) -> str:
    names = tuple(target_names)
    if not names:
        raise ValueError("target_names 不能为空")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("target_names 必须全部是非空字符串")
    return "、".join(names)


__all__ = [
    "CLIENT_UPDATE_ADMIN_ONLY",
    "CLIENT_UPDATE_ALREADY_SUBSCRIBED",
    "CLIENT_UPDATE_CONTEXT_UNAVAILABLE",
    "CLIENT_UPDATE_GROUP_ONLY",
    "CLIENT_UPDATE_GROUP_UNSUB_ONLY",
    "CLIENT_UPDATE_NOT_SUBSCRIBED",
    "CLIENT_UPDATE_SERVICE_UNAVAILABLE",
    "CLIENT_UPDATE_SUBSCRIBED",
    "CLIENT_UPDATE_SUBSCRIBED_RETRY",
    "CLIENT_UPDATE_SUBSCRIPTION_TYPE",
    "CLIENT_UPDATE_UNAVAILABLE",
    "CLIENT_UPDATE_UNSUBSCRIBED",
    "format_change",
    "format_current",
    "format_no_change",
    "format_size",
    "platform_name",
]
