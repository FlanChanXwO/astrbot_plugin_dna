"""玩家查询的用户可见文案。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip, get_tip_template

PLAYER_CONTEXT_UNAVAILABLE = get_tip("player.context_unavailable")
PLAYER_SERVICE_UNAVAILABLE = get_tip("player.service_unavailable")
PLAYER_UID_INVALID = get_tip("player.uid_invalid")
PLAYER_PEEK_BLOCKED = get_tip("player.peek_blocked")
PLAYER_ORIGINAL_UNSUPPORTED = get_tip("player.original_unsupported")
PLAYER_DAMAGE_FAILED = get_tip("player.damage_failed")
PLAYER_CACHE_STALE = get_tip("player.cache_stale")
PLAYER_CACHE_REFRESHED = get_tip("player.cache_refreshed")
PLAYER_INFO_CARD_REFRESHED = get_tip("player.info_card_refreshed")
PLAYER_INFO_CARD_CACHE_CLEARED = get_tip("player.info_card_cache_cleared")
PLAYER_CACHE_CLEARED = get_tip("player.cache_cleared")
PLAYER_ALL_ROLE_CACHE_CLEARED = get_tip("player.all_role_cache_cleared")
PLAYER_ROLE_CACHE_CLEARED = get_tip_template("player.role_cache_cleared")
PLAYER_ROLE_REFRESHED = get_tip_template("player.role_refreshed")
PLAYER_ALL_REFRESHED = get_tip_template("player.all_refreshed")
PLAYER_ADMIN_ONLY = get_tip("player.admin_only")
PLAYER_REFRESH_SELF_ONLY = get_tip("player.refresh_self_only")
PLAYER_OVERVIEW_NOT_FOUND = get_tip("player.overview_not_found")
PLAYER_ROLE_NOT_FOUND = get_tip("player.role_not_found")
PLAYER_ROLE_NOT_UNLOCKED = get_tip("player.role_not_unlocked")
PLAYER_WEAPON_NOT_FOUND = get_tip("player.weapon_not_found")
PLAYER_WEAPON_NOT_UNLOCKED = get_tip("player.weapon_not_unlocked")
PLAYER_WEAPON_CONFLICT = get_tip("player.weapon_conflict")
PLAYER_DETAIL_NOT_FOUND = get_tip("player.detail_not_found")
PLAYER_WEAPON_DETAIL_NOT_FOUND = get_tip("player.weapon_detail_not_found")


def account_not_bound(*, target: bool = False) -> str:
    """生成本地账号绑定缺失文案。"""

    return get_tip(
        "common.target_account_not_bound" if target else "common.account_not_bound"
    )


def transport_error(kind: str, *, target: bool = False) -> str:
    """将 transport 类别映射为不暴露服务端原文的文案。"""

    if kind == "credential":
        return get_tip(
            "common.credential_invalid" if target else "common.login_expired"
        )
    key = {
        "network": "player.transport_network",
        "status": "player.transport_status",
        "server": "player.transport_server",
        "not_found": "player.transport_not_found",
        "not_unlocked": "player.transport_not_unlocked",
    }.get(kind)
    return get_tip(key) if key else get_tip("common.service_unavailable")


def not_found(resource: str) -> str:
    return get_tip("player.not_found", resource=resource)


def not_unlocked(resource: str) -> str:
    return get_tip("player.not_unlocked", resource=resource)


def damage_config_missing(name: str) -> str:
    return get_tip("player.damage_config_missing", name=name)


def damage_not_open(name: str) -> str:
    return get_tip("player.damage_not_open", name=name)


def damage_role_level_unsupported(name: str, level: int) -> str:
    return get_tip(
        "player.damage_role_level_unsupported",
        name=name,
        level=level,
    )


def damage_weapon_level_unsupported(label: str, name: str, level: int) -> str:
    return get_tip(
        "player.damage_weapon_level_unsupported",
        label=label,
        name=name,
        level=level,
    )


__all__ = [
    "PLAYER_ADMIN_ONLY",
    "PLAYER_ALL_REFRESHED",
    "PLAYER_ALL_ROLE_CACHE_CLEARED",
    "PLAYER_CACHE_CLEARED",
    "PLAYER_CACHE_REFRESHED",
    "PLAYER_CACHE_STALE",
    "PLAYER_CONTEXT_UNAVAILABLE",
    "PLAYER_DAMAGE_FAILED",
    "PLAYER_DETAIL_NOT_FOUND",
    "PLAYER_INFO_CARD_CACHE_CLEARED",
    "PLAYER_INFO_CARD_REFRESHED",
    "PLAYER_ORIGINAL_UNSUPPORTED",
    "PLAYER_OVERVIEW_NOT_FOUND",
    "PLAYER_PEEK_BLOCKED",
    "PLAYER_REFRESH_SELF_ONLY",
    "PLAYER_ROLE_CACHE_CLEARED",
    "PLAYER_ROLE_NOT_FOUND",
    "PLAYER_ROLE_NOT_UNLOCKED",
    "PLAYER_ROLE_REFRESHED",
    "PLAYER_SERVICE_UNAVAILABLE",
    "PLAYER_UID_INVALID",
    "PLAYER_WEAPON_CONFLICT",
    "PLAYER_WEAPON_DETAIL_NOT_FOUND",
    "PLAYER_WEAPON_NOT_FOUND",
    "PLAYER_WEAPON_NOT_UNLOCKED",
    "account_not_bound",
    "damage_config_missing",
    "damage_not_open",
    "damage_role_level_unsupported",
    "damage_weapon_level_unsupported",
    "not_found",
    "not_unlocked",
    "transport_error",
]
