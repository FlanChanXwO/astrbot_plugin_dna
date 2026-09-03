"""玩家查询的用户可见文案。"""

from __future__ import annotations

PLAYER_CONTEXT_UNAVAILABLE = "玩家查询上下文不可用"
PLAYER_SERVICE_UNAVAILABLE = "玩家查询服务不可用"
PLAYER_UID_INVALID = "未登录或登录已失效，请重新登录"
PLAYER_PEEK_BLOCKED = "该用户开启了防偷窥，无法查看其游戏信息"
PLAYER_ORIGINAL_UNSUPPORTED = "当前平台暂不支持通过引用获取角色原图"
PLAYER_DAMAGE_FAILED = "伤害计算暂不可用，请稍后再试"
PLAYER_CACHE_CLEARED = "角色缓存已清理"
PLAYER_ALL_ROLE_CACHE_CLEARED = "当前 UID 的全部角色缓存已清理"
PLAYER_ROLE_CACHE_CLEARED = "角色【{name}】缓存已清理"
PLAYER_ALL_REFRESHED = "角色面板刷新完成：成功 {success} 个，失败 {failed} 个"
PLAYER_ADMIN_ONLY = "该命令仅限管理员使用"
PLAYER_REFRESH_SELF_ONLY = "普通用户只能刷新自己的角色面板"
PLAYER_OVERVIEW_NOT_FOUND = "角色列表信息未找到，请检查账号是否有效"
PLAYER_ROLE_NOT_FOUND = "角色未找到，请检查角色名是否正确"
PLAYER_ROLE_NOT_UNLOCKED = "当前角色暂未拥有，无法查看"
PLAYER_WEAPON_NOT_FOUND = "展柜武器未找到，请检查武器名是否正确"
PLAYER_WEAPON_NOT_UNLOCKED = "当前展柜武器暂未拥有，无法查看"
PLAYER_WEAPON_CONFLICT = "角色面板最多携带一把近战武器和一把远程武器"
PLAYER_DETAIL_NOT_FOUND = "角色详情未找到，请检查账号是否有效"
PLAYER_WEAPON_DETAIL_NOT_FOUND = "武器详情未找到，请检查账号是否有效"


def transport_error(kind: str) -> str:
    """将 transport 类别映射为不暴露服务端原文的文案。"""

    return {
        "network": "玩家数据网络请求失败",
        "status": "玩家数据服务状态异常",
        "server": "玩家数据服务响应异常",
        "not_found": "玩家数据未找到",
        "not_unlocked": "当前数据暂未拥有，无法查看",
    }.get(kind, "玩家数据读取失败")


__all__ = [
    "PLAYER_ADMIN_ONLY",
    "PLAYER_ALL_REFRESHED",
    "PLAYER_ALL_ROLE_CACHE_CLEARED",
    "PLAYER_CACHE_CLEARED",
    "PLAYER_CONTEXT_UNAVAILABLE",
    "PLAYER_DAMAGE_FAILED",
    "PLAYER_DETAIL_NOT_FOUND",
    "PLAYER_ORIGINAL_UNSUPPORTED",
    "PLAYER_OVERVIEW_NOT_FOUND",
    "PLAYER_PEEK_BLOCKED",
    "PLAYER_REFRESH_SELF_ONLY",
    "PLAYER_ROLE_CACHE_CLEARED",
    "PLAYER_ROLE_NOT_FOUND",
    "PLAYER_ROLE_NOT_UNLOCKED",
    "PLAYER_SERVICE_UNAVAILABLE",
    "PLAYER_UID_INVALID",
    "PLAYER_WEAPON_CONFLICT",
    "PLAYER_WEAPON_DETAIL_NOT_FOUND",
    "PLAYER_WEAPON_NOT_FOUND",
    "PLAYER_WEAPON_NOT_UNLOCKED",
    "transport_error",
]
