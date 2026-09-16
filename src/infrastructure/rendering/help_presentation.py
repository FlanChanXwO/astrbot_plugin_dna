"""帮助卡片的 presentation 映射。

帮助菜单的分组、展示名、图标和排序属于 UI 关注点，与业务 CommandSpec
解耦：业务声明只保留 id/pattern/permission/use case，展示信息统一以
稳定的 command id 为键在这里维护。渲染层禁止再用中文命令名猜测图标。

- ``HELP_PRESENTATION``：每个帮助可见命令的显式展示配置；缺少条目视为
  配置错误，渲染边界显式失败。
- ``HELP_GROUP_ORDER``：帮助分组的产品约定顺序（普通用户 10 组 + 管理员
  追加 3 组）。
- 图标文件位于 ``src/resources/help/icon_path/``；条目引用的图标必须存在。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HelpPresentationEntry:
    """单个命令在帮助卡片中的展示信息。"""

    group: str
    name: str
    icon: str


GROUP_INFO_QUERY = "信息查询"
GROUP_ACCOUNT = "账号管理"
GROUP_INFO_CARD = "基础卡片"
GROUP_ROLE_PANEL = "角色面板"
GROUP_DAILY = "日常查询"
GROUP_ENCYCLOPEDIA = "图鉴攻略"
GROUP_MH = "密函"
GROUP_SIGN = "签到"
GROUP_NOTICE_UPDATE = "公告与更新"
GROUP_PRIVACY = "隐私设置"
GROUP_ADMIN_PRIVACY = "群隐私管理"
GROUP_ADMIN_PUSH = "推送与签到管理"
GROUP_ADMIN_RESOURCE = "资源与维护"

HELP_GROUP_ORDER: tuple[str, ...] = (
    GROUP_INFO_QUERY,
    GROUP_ACCOUNT,
    GROUP_INFO_CARD,
    GROUP_ROLE_PANEL,
    GROUP_DAILY,
    GROUP_ENCYCLOPEDIA,
    GROUP_MH,
    GROUP_SIGN,
    GROUP_NOTICE_UPDATE,
    GROUP_PRIVACY,
    GROUP_ADMIN_PRIVACY,
    GROUP_ADMIN_PUSH,
    GROUP_ADMIN_RESOURCE,
)

ADMIN_HELP_GROUPS: frozenset[str] = frozenset(
    {
        GROUP_ADMIN_PRIVACY,
        GROUP_ADMIN_PUSH,
        GROUP_ADMIN_RESOURCE,
    }
)

HELP_GROUP_DESCRIPTIONS: dict[str, str] = {
    GROUP_INFO_QUERY: "查看帮助信息",
    GROUP_ACCOUNT: "登录后才能查询；支持切换、删除 UID 与凭证管理",
    GROUP_INFO_CARD: "查看和刷新基本信息卡片",
    GROUP_ROLE_PANEL: "查看角色详情，刷新和清理角色面板缓存",
    GROUP_DAILY: "日常状态、周报和日历",
    GROUP_ENCYCLOPEDIA: "图鉴、别名、角色攻略和兑换码",
    GROUP_MH: "查询、订阅和设置密函推送",
    GROUP_SIGN: "手动签到、签到日历和自动签到开关",
    GROUP_NOTICE_UPDATE: "查看公告和客户端更新",
    GROUP_PRIVACY: "控制他人查询你的游戏信息和 UID",
    GROUP_ADMIN_PRIVACY: "管理本群成员与全体的隐私策略",
    GROUP_ADMIN_PUSH: "管理签到与公告、客户端更新的订阅推送",
    GROUP_ADMIN_RESOURCE: "别名维护与资源管理",
}

HELP_PRESENTATION: dict[str, HelpPresentationEntry] = {
    # 信息查询
    "help": HelpPresentationEntry(GROUP_INFO_QUERY, "帮助", "帮助.png"),
    # 账号管理
    "account_login": HelpPresentationEntry(GROUP_ACCOUNT, "登录", "登录.png"),
    "account_logout": HelpPresentationEntry(GROUP_ACCOUNT, "退出登录", "退出登录.png"),
    "account_list": HelpPresentationEntry(GROUP_ACCOUNT, "查看UID", "查看UID.png"),
    "account_switch": HelpPresentationEntry(GROUP_ACCOUNT, "切换UID", "切换UID.png"),
    "account_delete": HelpPresentationEntry(GROUP_ACCOUNT, "删除UID", "删除UID.png"),
    "account_delete_all": HelpPresentationEntry(
        GROUP_ACCOUNT, "删除全部UID", "删除全部UID.png"
    ),
    "account_credentials": HelpPresentationEntry(
        GROUP_ACCOUNT, "获取凭证", "获取绑定的token.png"
    ),
    "account_check_credentials": HelpPresentationEntry(
        GROUP_ACCOUNT, "检查凭证", "查看UID.png"
    ),
    # 基础卡片
    "role_info_card": HelpPresentationEntry(
        GROUP_INFO_CARD, "基本信息卡片", "基本信息.png"
    ),
    "refresh_info_card_cache": HelpPresentationEntry(
        GROUP_INFO_CARD, "刷新卡片", "卡片.png"
    ),
    "clear_info_card_cache": HelpPresentationEntry(
        GROUP_INFO_CARD, "清理卡片缓存", "卡片.png"
    ),
    # 角色面板
    "role_detail_card": HelpPresentationEntry(
        GROUP_ROLE_PANEL, "角色详情卡片", "角色面板.png"
    ),
    "refresh_role_card": HelpPresentationEntry(
        GROUP_ROLE_PANEL, "刷新角色面板", "角色面板.png"
    ),
    "refresh_all_role_cards": HelpPresentationEntry(
        GROUP_ROLE_PANEL, "刷新全部角色面板", "角色面板.png"
    ),
    "clear_role_cache": HelpPresentationEntry(
        GROUP_ROLE_PANEL, "清理角色面板缓存", "角色面板.png"
    ),
    "clear_player_cache": HelpPresentationEntry(
        GROUP_ROLE_PANEL, "清理全部角色缓存", "角色面板.png"
    ),
    # 日常查询
    "stamina": HelpPresentationEntry(GROUP_DAILY, "日常便签", "体力.png"),
    "weekly_report_current": HelpPresentationEntry(GROUP_DAILY, "本周周报", "日常.png"),
    "weekly_report_last": HelpPresentationEntry(GROUP_DAILY, "上周周报", "日常.png"),
    "calendar": HelpPresentationEntry(GROUP_DAILY, "日历", "日历.png"),
    # 图鉴攻略
    "dna_wiki": HelpPresentationEntry(GROUP_ENCYCLOPEDIA, "图鉴", "图鉴.png"),
    "alias_all_list": HelpPresentationEntry(
        GROUP_ENCYCLOPEDIA, "角色/武器列表", "武器别名.png"
    ),
    "alias_list": HelpPresentationEntry(GROUP_ENCYCLOPEDIA, "别名列表", "角色别名.png"),
    "dna_guide": HelpPresentationEntry(GROUP_ENCYCLOPEDIA, "角色攻略", "角色攻略.png"),
    "dna_code": HelpPresentationEntry(GROUP_ENCYCLOPEDIA, "兑换码", "兑换码.png"),
    # 密函
    "mh": HelpPresentationEntry(GROUP_MH, "密函", "查看当前密函.png"),
    "mh_list": HelpPresentationEntry(GROUP_MH, "密函列表", "所有密函列表.png"),
    "mh_subscribe_by_name": HelpPresentationEntry(
        GROUP_MH, "订阅/退订密函", "订阅指定密函推送.png"
    ),
    "mh_subscribe_cycle": HelpPresentationEntry(
        GROUP_MH, "设置密函推送时间", "订阅密函推送周期.png"
    ),
    "mh_subscribe": HelpPresentationEntry(GROUP_MH, "我的密函", "我的密函订阅.png"),
    "mh_pic_subscribe": HelpPresentationEntry(
        GROUP_MH, "订阅密函图片", "订阅密函图片.png"
    ),
    "mh_text_subscribe": HelpPresentationEntry(
        GROUP_MH, "订阅密函文本", "订阅角色密函推送.png"
    ),
    # 签到
    "sign": HelpPresentationEntry(GROUP_SIGN, "签到", "签到.png"),
    "sign_calendar": HelpPresentationEntry(GROUP_SIGN, "签到日历", "签到日历.png"),
    "sign_auto_enable": HelpPresentationEntry(
        GROUP_SIGN, "开启自动签到", "开启自动签到.png"
    ),
    "sign_auto_disable": HelpPresentationEntry(
        GROUP_SIGN, "关闭自动签到", "关闭自动签到.png"
    ),
    # 公告与更新
    "ann": HelpPresentationEntry(GROUP_NOTICE_UPDATE, "公告", "订阅公告.png"),
    "client_update": HelpPresentationEntry(
        GROUP_NOTICE_UPDATE, "客户端更新", "git更新记录.png"
    ),
    # 隐私设置
    "privacy_enable_peek_personal": HelpPresentationEntry(
        GROUP_PRIVACY, "开偷窥", "开偷窥.png"
    ),
    "privacy_disable_peek_personal": HelpPresentationEntry(
        GROUP_PRIVACY, "防偷窥", "防偷窥.png"
    ),
    "privacy_enable_uid_hidden": HelpPresentationEntry(
        GROUP_PRIVACY, "隐藏UID", "UID.png"
    ),
    "privacy_disable_uid_hidden": HelpPresentationEntry(
        GROUP_PRIVACY, "显示UID", "UID.png"
    ),
    # 群隐私管理（管理员）
    "privacy_enable_peek_admin": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "指定开偷窥", "开偷窥.png"
    ),
    "privacy_disable_peek_admin": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "指定防偷窥", "防偷窥.png"
    ),
    "privacy_enable_peek_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "全体开偷窥", "全体开偷窥.png"
    ),
    "privacy_disable_peek_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "全体防偷窥", "全体防偷窥.png"
    ),
    "privacy_cancel_peek_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "取消全体偷窥", "取消全体偷窥.png"
    ),
    "privacy_enable_uid_hidden_admin": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "指定隐藏UID", "UID.png"
    ),
    "privacy_disable_uid_hidden_admin": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "指定显示UID", "UID.png"
    ),
    "privacy_enable_uid_hidden_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "全体隐藏UID", "UID.png"
    ),
    "privacy_disable_uid_hidden_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "全体显示UID", "UID.png"
    ),
    "privacy_cancel_uid_hidden_all": HelpPresentationEntry(
        GROUP_ADMIN_PRIVACY, "取消全体UID隐藏", "UID.png"
    ),
    # 推送与签到管理（管理员）
    "sign_all": HelpPresentationEntry(GROUP_ADMIN_PUSH, "全部签到", "全部重新签到.png"),
    "sign_result_subscribe": HelpPresentationEntry(
        GROUP_ADMIN_PUSH, "订阅签到结果", "订阅自动签到结果.png"
    ),
    "sign_group_report_subscribe": HelpPresentationEntry(
        GROUP_ADMIN_PUSH, "订阅本群签到报告", "订阅自动签到结果.png"
    ),
    "ann_sub": HelpPresentationEntry(GROUP_ADMIN_PUSH, "订阅公告", "订阅公告.png"),
    "ann_unsub": HelpPresentationEntry(
        GROUP_ADMIN_PUSH, "取消订阅公告", "取消订阅公告.png"
    ),
    "client_update_subscribe": HelpPresentationEntry(
        GROUP_ADMIN_PUSH, "订阅客户端更新", "订阅公告.png"
    ),
    "client_update_unsubscribe": HelpPresentationEntry(
        GROUP_ADMIN_PUSH, "退订客户端更新", "取消订阅公告.png"
    ),
    # 资源与维护（管理员）
    "alias_add_delete": HelpPresentationEntry(
        GROUP_ADMIN_RESOURCE, "添加/删除别名", "角色别名.png"
    ),
    "alias_recover": HelpPresentationEntry(
        GROUP_ADMIN_RESOURCE, "恢复别名", "恢复别名.png"
    ),
    "resource_status": HelpPresentationEntry(
        GROUP_ADMIN_RESOURCE, "资源状态", "资源状态.png"
    ),
    "download_resource": HelpPresentationEntry(
        GROUP_ADMIN_RESOURCE, "同步资源", "同步资源.png"
    ),
}

# 展示顺序以 presentation 声明顺序为准，与业务模块的声明顺序解耦。
_HELP_DISPLAY_ORDER: dict[str, int] = {
    command_id: index for index, command_id in enumerate(HELP_PRESENTATION)
}


def get_presentation(command_id: str) -> HelpPresentationEntry:
    """取得命令的展示配置；缺少配置是注册期错误，不允许静默兜底。"""

    try:
        return HELP_PRESENTATION[command_id]
    except KeyError:
        raise KeyError(
            f"命令 {command_id} 缺少帮助 presentation 配置；"
            "请在 help_presentation.HELP_PRESENTATION 中显式登记",
        ) from None


def display_rank(command_id: str) -> int:
    """返回命令在帮助分组内的展示顺序。"""

    return _HELP_DISPLAY_ORDER.get(command_id, len(_HELP_DISPLAY_ORDER))


__all__ = [
    "ADMIN_HELP_GROUPS",
    "HELP_GROUP_DESCRIPTIONS",
    "HELP_GROUP_ORDER",
    "HELP_PRESENTATION",
    "HelpPresentationEntry",
    "display_rank",
    "get_presentation",
]
