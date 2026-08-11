"""隐私 use case 的用户可见文案。"""

from __future__ import annotations

PRIVACY_CONTEXT_UNAVAILABLE = "无法识别当前用户，暂不能执行隐私操作！"
PRIVACY_SERVICE_UNAVAILABLE = "隐私服务尚未初始化，请稍后再试！"
GROUP_REQUIRED = "请在群聊中使用此命令"
TARGET_PEEK_ENABLE_REQUIRED = "请@要允许被查看的玩家"
TARGET_PEEK_DISABLE_REQUIRED = "请@要禁止被查看的玩家"
TARGET_UID_ENABLE_REQUIRED = "请@要隐藏UID的玩家"
TARGET_UID_DISABLE_REQUIRED = "请@要显示UID的玩家"
TARGET_NOT_BOUND = "该用户未绑定UID"

PERSONAL_PEEK_ENABLED = "已允许他人查看你的游戏信息~"
PERSONAL_PEEK_DISABLED = "已禁止他人查看你的游戏信息~"
TARGET_PEEK_ENABLED = "已允许该用户被他人查看游戏信息~"
TARGET_PEEK_DISABLED = "已禁止该用户被他人查看游戏信息~"
GROUP_PEEK_ENABLED = "已开启全体允许查看模式，群内所有玩家均可被查看游戏信息~"
GROUP_PEEK_DISABLED = "已开启全体禁止查看模式，群内所有玩家均无法被他人查看游戏信息~"
GROUP_PEEK_CANCELLED = "已取消全体查看权限设置，恢复个人设置~"

PERSONAL_UID_ENABLED = "已隐藏你的UID，其他人将无法查看~"
PERSONAL_UID_DISABLED = "已显示你的UID，其他人现在可以查看~"
TARGET_UID_ENABLED = "已为该用户隐藏UID~"
TARGET_UID_DISABLED = "已为该用户显示UID~"
GROUP_UID_ENABLED = "已开启全体隐藏UID模式，群内所有玩家的UID将被隐藏~"
GROUP_UID_DISABLED = "已开启全体显示UID模式，群内所有玩家的UID将被显示~"
GROUP_UID_CANCELLED = "已取消全体UID显示设置，恢复个人设置~"


def personal_peek_blocked(force_allow_peek: bool) -> str:
    """返回群强制偷窥值对应的个人修改阻止原因。"""

    if force_allow_peek:
        return "当前群已开启全体允许被查看，无法修改个人设置"
    return "当前群已开启全体防偷窥，无法修改个人设置"


def personal_uid_blocked(force_uid_hidden: bool) -> str:
    """返回群强制 UID 值对应的个人修改阻止原因。"""

    if force_uid_hidden:
        return "当前群已开启全体隐藏UID，无法修改个人设置"
    return "当前群已开启全体显示UID，无法修改个人设置"


__all__ = [
    "GROUP_PEEK_CANCELLED",
    "GROUP_PEEK_DISABLED",
    "GROUP_PEEK_ENABLED",
    "GROUP_REQUIRED",
    "GROUP_UID_CANCELLED",
    "GROUP_UID_DISABLED",
    "GROUP_UID_ENABLED",
    "PERSONAL_PEEK_DISABLED",
    "PERSONAL_PEEK_ENABLED",
    "PERSONAL_UID_DISABLED",
    "PERSONAL_UID_ENABLED",
    "PRIVACY_CONTEXT_UNAVAILABLE",
    "PRIVACY_SERVICE_UNAVAILABLE",
    "TARGET_NOT_BOUND",
    "TARGET_PEEK_DISABLE_REQUIRED",
    "TARGET_PEEK_DISABLED",
    "TARGET_PEEK_ENABLE_REQUIRED",
    "TARGET_PEEK_ENABLED",
    "TARGET_UID_DISABLE_REQUIRED",
    "TARGET_UID_DISABLED",
    "TARGET_UID_ENABLE_REQUIRED",
    "TARGET_UID_ENABLED",
    "personal_peek_blocked",
    "personal_uid_blocked",
]
