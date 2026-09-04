"""客户端更新命令、订阅与查询结果的用户可见文案。"""

from __future__ import annotations

from .contracts import ClientPlatform, ClientUpdateChange, ClientVersionSnapshot

CLIENT_UPDATE_CONTEXT_UNAVAILABLE = "客户端更新查询上下文不可用"
CLIENT_UPDATE_SERVICE_UNAVAILABLE = "客户端更新服务不可用"
CLIENT_UPDATE_ADMIN_ONLY = "仅群管理员可管理客户端更新订阅"
CLIENT_UPDATE_GROUP_ONLY = "请在群聊中订阅客户端更新"
CLIENT_UPDATE_GROUP_UNSUB_ONLY = "请在群聊中取消订阅客户端更新"
CLIENT_UPDATE_PLATFORM_INVALID = "客户端更新平台不正确，请使用 PC 或 安卓"
CLIENT_UPDATE_UNAVAILABLE = "客户端更新暂时无法获取"

CLIENT_UPDATE_SUBSCRIPTION_TYPE = "订阅DNA客户端更新"
CLIENT_UPDATE_ALREADY_SUBSCRIBED = "已经订阅客户端更新，已更新平台筛选"
CLIENT_UPDATE_SUBSCRIBED = "成功订阅客户端更新！"
CLIENT_UPDATE_SUBSCRIBED_RETRY = (
    "已保存客户端更新订阅，首次检查暂时失败，将在下次检查重试。"
)
CLIENT_UPDATE_UNSUBSCRIBED = "成功取消订阅客户端更新！"
CLIENT_UPDATE_NOT_SUBSCRIBED = "未曾订阅客户端更新！"

_DETECTED_PREFIX = "检测到二重螺旋"

_PLATFORM_NAMES = {
    ClientPlatform.PC: "PC",
    ClientPlatform.ANDROID: "安卓",
}


def platform_name(platform: ClientPlatform) -> str:
    """返回面向用户的稳定平台名称。"""

    return _PLATFORM_NAMES[ClientPlatform(platform)]


def format_current(snapshot: ClientVersionSnapshot) -> str:
    """格式化没有可比较基线时的当前版本。"""

    return (
        f"{_DETECTED_PREFIX}"
        f"国服 {platform_name(snapshot.platform)} 客户端\n"
        f"当前版本：{snapshot.version_text}"
    )


def format_no_change(snapshot: ClientVersionSnapshot) -> str:
    """格式化已有基线但版本未变化的查询结果。"""

    return f"{format_current(snapshot)}\n暂无更新"


def format_change(change: ClientUpdateChange) -> str:
    """格式化一次已确认的版本变化。"""

    return (
        f"{_DETECTED_PREFIX}"
        f"国服 {platform_name(change.platform)} 客户端更新\n"
        f"版本：{change.previous.version_text} → {change.current.version_text}\n"
        f"新增更新：{format_size(change.added_size_bytes)}"
    )


def format_size(size_bytes: int) -> str:
    """把字节数格式化为适合聊天消息的单位。"""

    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.2f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


__all__ = [
    "CLIENT_UPDATE_ADMIN_ONLY",
    "CLIENT_UPDATE_ALREADY_SUBSCRIBED",
    "CLIENT_UPDATE_CONTEXT_UNAVAILABLE",
    "CLIENT_UPDATE_GROUP_ONLY",
    "CLIENT_UPDATE_GROUP_UNSUB_ONLY",
    "CLIENT_UPDATE_NOT_SUBSCRIBED",
    "CLIENT_UPDATE_PLATFORM_INVALID",
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
