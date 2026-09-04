"""隐私 use case 的用户可见文案兼容层。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip

PRIVACY_CONTEXT_UNAVAILABLE = get_tip("privacy.context_unavailable")
PRIVACY_SERVICE_UNAVAILABLE = get_tip("privacy.service_unavailable")
GROUP_REQUIRED = get_tip("privacy.group_required")
TARGET_PEEK_ENABLE_REQUIRED = get_tip("privacy.target_peek_enable_required")
TARGET_PEEK_DISABLE_REQUIRED = get_tip("privacy.target_peek_disable_required")
TARGET_UID_ENABLE_REQUIRED = get_tip("privacy.target_uid_enable_required")
TARGET_UID_DISABLE_REQUIRED = get_tip("privacy.target_uid_disable_required")
TARGET_NOT_BOUND = get_tip("privacy.target_not_bound")
PERSONAL_PEEK_ENABLED = get_tip("privacy.personal_peek_enabled")
PERSONAL_PEEK_DISABLED = get_tip("privacy.personal_peek_disabled")
TARGET_PEEK_ENABLED = get_tip("privacy.target_peek_enabled")
TARGET_PEEK_DISABLED = get_tip("privacy.target_peek_disabled")
GROUP_PEEK_ENABLED = get_tip("privacy.group_peek_enabled")
GROUP_PEEK_DISABLED = get_tip("privacy.group_peek_disabled")
GROUP_PEEK_CANCELLED = get_tip("privacy.group_peek_cancelled")
PERSONAL_UID_ENABLED = get_tip("privacy.personal_uid_enabled")
PERSONAL_UID_DISABLED = get_tip("privacy.personal_uid_disabled")
TARGET_UID_ENABLED = get_tip("privacy.target_uid_enabled")
TARGET_UID_DISABLED = get_tip("privacy.target_uid_disabled")
GROUP_UID_ENABLED = get_tip("privacy.group_uid_enabled")
GROUP_UID_DISABLED = get_tip("privacy.group_uid_disabled")
GROUP_UID_CANCELLED = get_tip("privacy.group_uid_cancelled")


def personal_peek_blocked(force_allow_peek: bool) -> str:
    """返回群强制偷窥值对应的个人修改阻止原因。"""

    return get_tip(
        "privacy.personal_peek_blocked_allow"
        if force_allow_peek
        else "privacy.personal_peek_blocked_deny"
    )


def personal_uid_blocked(force_uid_hidden: bool) -> str:
    """返回群强制 UID 值对应的个人修改阻止原因。"""

    return get_tip(
        "privacy.personal_uid_blocked_hidden"
        if force_uid_hidden
        else "privacy.personal_uid_blocked_visible"
    )


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
    "TARGET_PEEK_DISABLED",
    "TARGET_PEEK_DISABLE_REQUIRED",
    "TARGET_PEEK_ENABLED",
    "TARGET_PEEK_ENABLE_REQUIRED",
    "TARGET_UID_DISABLED",
    "TARGET_UID_DISABLE_REQUIRED",
    "TARGET_UID_ENABLED",
    "TARGET_UID_ENABLE_REQUIRED",
    "personal_peek_blocked",
    "personal_uid_blocked",
]
