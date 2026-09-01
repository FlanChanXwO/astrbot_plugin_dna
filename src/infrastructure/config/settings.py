"""v0.1 typed 配置定义。

配置模型只描述插件自己的领域配置，不依赖 AstrBot 的事件、命令或
``Context``。AstrBot 的嵌套字典在边界处通过 :meth:`DnabySettings.from_config`
转换为这些模型，避免业务代码继续直接操作未类型化的配置字典。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ..resources.acceleration import (
    GithubAccelerationMode,
    normalize_http_base_url,
    resolve_github_acceleration_prefix,
)
from .legacy import _LEGACY_MAP, DNA_PREFIX, DNAConfig, DNASignConfig

logger = logging.getLogger(__name__)
_REMOVED_MH_LEGACY_KEYS = frozenset(("MHPushSubscribe", "MHCache"))
_REMOVED_MH_TYPED_FIELDS = frozenset(("secret_push_time", "secret_cache"))


class _SettingsModel(BaseModel):
    """所有配置分组共用的校验策略。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LoginSettings(_SettingsModel):
    """登录接入和未登录账号容量配置。"""

    url: str = Field(
        default="",
        description="登录服务地址",
        json_schema_extra={
            "hint": "登录页或外置 dna-login 服务的 base URL；留空使用内置服务"
        },
    )
    bind_host: str = Field(
        default="127.0.0.1",
        description="内置服务监听地址",
        json_schema_extra={"hint": "内置登录服务监听地址"},
    )
    port: int = Field(
        default=6189,
        ge=0,
        le=65535,
        description="内置服务监听端口",
        json_schema_extra={"hint": "内置登录服务监听端口；0 表示由系统分配临时端口"},
    )
    transport: Literal["local", "http_poll", "sse", "ws"] = Field(
        default="local",
        description="登录接入方式",
        json_schema_extra={"hint": "登录接入方式 (local/http_poll/sse/ws)"},
    )
    shared_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        description="外置服务共享密钥",
        json_schema_extra={"hint": "外置登录服务共享密钥；不会写入日志或用户响应"},
    )
    tencent_docs: bool = Field(
        default=False,
        description="腾讯文档登录辅助",
        json_schema_extra={"hint": "是否启用腾讯文档登录辅助"},
    )
    qr_login: bool = Field(
        default=False,
        description="二维码登录",
        json_schema_extra={"hint": "是否将登录链接转换为二维码"},
    )
    forward_login: bool = Field(
        default=False,
        description="转发消息登录",
        json_schema_extra={"hint": "是否将登录链接转换为转发消息"},
    )
    max_bind_count: int = Field(
        default=2,
        ge=0,
        le=100,
        description="未登录用户最大绑定数",
        json_schema_extra={"hint": "未登录用户允许绑定的 UID 数量"},
    )


class NetworkSettings(_SettingsModel):
    """API、代理和 WebSocket 连接配置。"""

    max_concurrent_requests: int = Field(
        default=4,
        ge=1,
        description="短请求最大并发数",
        json_schema_extra={
            "hint": "限制 API、图片等短生命周期网络请求；WebSocket/SSE 不长期占用",
        },
    )

    api_proxy_url: str = Field(
        default="",
        description="API 代理地址",
        json_schema_extra={"hint": "二重螺旋 API 代理地址"},
    )
    local_proxy_url: str = Field(
        default="",
        description="本地代理地址",
        json_schema_extra={"hint": "本地代理地址"},
    )
    proxy_functions: list[Literal["all", "get_sms_code", "login"]] = Field(
        default_factory=list,
        description="指定走代理的函数",
        json_schema_extra={"hint": "需要使用代理的函数；空列表表示不额外指定"},
    )
    no_proxy_functions: list[str] = Field(
        default_factory=list,
        description="强制直连的函数",
        json_schema_extra={"hint": "强制不使用代理的函数，优先级高于 proxy_functions"},
    )
    websocket_continue_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="WebSocket 保活时间",
        json_schema_extra={"hint": "WebSocket 保活持续时间（秒）"},
    )
    websocket_wait_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="WebSocket 连接等待时间",
        json_schema_extra={"hint": "等待 WebSocket 建立连接的时间（秒）"},
    )


class ResourceSettings(_SettingsModel):
    """公共资源仓库下载和 GitHub 加速配置。"""

    # Pydantic 默认会把无效字段的原始 input 写进 ValidationError 文本；加速 URL
    # 可能包含凭据样式内容，因此该配置组必须隐藏原始输入，避免错误回显。
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        hide_input_in_errors=True,
    )

    github_acceleration: GithubAccelerationMode = Field(
        default="off",
        description="GitHub 资源加速模式",
        json_schema_extra={
            "hint": "默认直连；镜像失败会直接报告，不自动回退直连",
        },
    )
    custom_github_acceleration_url: str = Field(
        default="",
        description="自定义 GitHub 加速前缀",
        json_schema_extra={
            "hint": "仅 custom 模式使用；填写不含 query、fragment 或凭据的 HTTP(S) 基础 URL",
        },
    )

    @field_validator("custom_github_acceleration_url", mode="before")
    @classmethod
    def _normalize_custom_url(cls, value: Any) -> str:
        return normalize_http_base_url(value)

    @model_validator(mode="after")
    def _validate_custom_mode(self) -> ResourceSettings:
        if (
            self.github_acceleration == "custom"
            and not self.custom_github_acceleration_url
        ):
            raise ValueError("custom 模式必须配置自定义 GitHub 加速前缀")
        return self

    @property
    def acceleration_prefix(self) -> str | None:
        """返回本次资源 Git/Raw 请求应使用的加速前缀。"""

        return resolve_github_acceleration_prefix(
            self.github_acceleration,
            self.custom_github_acceleration_url,
        )


class CacheSettings(_SettingsModel):
    """统一文件缓存的时间和发送策略。"""

    fresh_ttl_minutes: int = Field(
        default=30,
        ge=0,
        description="缓存 fresh 保持时间（分钟）",
        json_schema_extra={"hint": "缓存内容在此时间内视为 fresh"},
    )
    retention_ttl_hours: int = Field(
        default=24,
        gt=0,
        description="缓存硬保留时间（小时）",
        json_schema_extra={"hint": "缓存超过此时间后允许清理"},
    )
    announcement_ttl_hours: int = Field(
        default=24,
        gt=0,
        description="公告缓存保留时间（小时）",
        json_schema_extra={"hint": "公告缓存的绝对保留时间"},
    )
    refresh_send_card: bool = Field(
        default=True,
        description="刷新后发送卡片",
        json_schema_extra={"hint": "刷新成功后是否立即发送新卡片"},
    )


class AgentToolsSettings(_SettingsModel):
    """AstrBot Agent Tools 的总开关。"""

    enabled: bool = Field(
        default=False,
        description="Agent Tools 总开关",
        json_schema_extra={"hint": "是否注册二重螺旋 Agent Tools"},
    )


class SignInSettings(_SettingsModel):
    """游戏签到、社区任务和签到报告配置。"""

    community_tasks: list[
        Literal["bbs_sign", "bbs_detail", "bbs_like", "bbs_share", "bbs_reply"]
    ] = Field(
        default_factory=lambda: [
            "bbs_sign",
            "bbs_detail",
            "bbs_like",
            "bbs_share",
            "bbs_reply",
        ],
        description="启用的社区任务",
        json_schema_extra={"hint": "启用的社区任务列表"},
    )
    enable_all_users: bool = Field(
        default=False,
        description="全员自动签到",
        json_schema_extra={"hint": "是否为所有已登录用户自动执行签到"},
    )
    scheduled_enabled: bool = Field(
        default=False,
        description="定时签到开关",
        json_schema_extra={"hint": "是否启用定时签到"},
    )
    sign_time: str = Field(
        default="00:05",
        description="每日签到时间",
        json_schema_extra={"hint": "每日签到时间，格式为 HH:mm（如 00:05）"},
    )

    @field_validator("sign_time", mode="before")
    @classmethod
    def _validate_sign_time(cls, value: Any) -> str:
        # 显式配置错误必须在启动边界暴露，不能静默落到签到默认时间。
        if isinstance(value, str):
            parts = value.strip().split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hour, minute = int(parts[0]), int(parts[1])
            else:
                raise ValueError("sign_time 必须为有效的 HH:mm 时间")
        elif isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                hour, minute = int(value[0]), int(value[1])
            except (ValueError, TypeError) as error:
                raise ValueError("sign_time 必须为有效的 HH:mm 时间") from error
        else:
            raise ValueError("sign_time 必须为有效的 HH:mm 时间")
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("sign_time 必须为有效的 HH:mm 时间")
        return f"{hour:02d}:{minute:02d}"

    concurrency: int = Field(
        default=1,
        ge=1,
        le=50,
        description="签到并发数",
        json_schema_extra={"hint": "自动签到并发数量"},
    )
    concurrency_interval_seconds: tuple[int, int] = Field(
        default=(3, 5),
        description="签到任务随机间隔",
        json_schema_extra={"hint": "自动签到任务之间的随机间隔范围（秒）"},
    )
    private_report: bool = Field(
        default=False,
        description="私聊签到报告",
        json_schema_extra={"hint": "是否发送签到私聊报告"},
    )
    group_report: bool = Field(
        default=False,
        description="群聊签到报告",
        json_schema_extra={"hint": "是否发送签到群组报告"},
    )
    group_report_image: bool = Field(
        default=False,
        description="图片形式群报告",
        json_schema_extra={"hint": "是否以图片发送群组报告"},
    )


class NotificationSettings(_SettingsModel):
    """公告和密函通知配置。"""

    announcement_enabled: bool = Field(
        default=True,
        description="公告推送开关",
        json_schema_extra={"hint": "是否启用公告推送"},
    )
    announcement_groups: dict[str, Any] = Field(
        default_factory=dict,
        description="公告推送群组",
        json_schema_extra={
            "hint": "公告推送群组配置（群内输入 kk订阅公告 也会自动同步到此处）"
        },
    )
    announcement_ids: list[int] = Field(
        default_factory=list,
        description="已推送公告ID",
        json_schema_extra={"hint": "已经推送过的公告 ID 列表"},
    )
    announcement_check_minutes: int = Field(
        default=10,
        ge=0,
        le=60,
        description="公告检查间隔",
        json_schema_extra={"hint": "公告推送检查间隔（分钟）"},
    )
    secret_subscriptions: list[Literal["private", "group"]] = Field(
        default_factory=lambda: ["group"],
        description="密函订阅作用域",
        json_schema_extra={"hint": "密函订阅作用域 (private/group)"},
    )
    secret_simple_image: bool = Field(
        default=False,
        description="简易密函图片",
        json_schema_extra={"hint": "是否使用简单密函图片"},
    )


class DisplaySettings(_SettingsModel):
    """角色展示、攻略来源和 AT 查询配置。"""

    command_prefixes: list[str] = Field(
        default_factory=lambda: ["kk"],
        description="命令触发前缀列表",
        json_schema_extra={
            "hint": "插件支持的命令触发前缀列表，如 ['kk', 'dna']；列表含空字符串时允许无前缀触发"
        },
    )
    guide_providers: list[Literal["all", "狩月庭攻略组", "猫冬"]] = Field(
        default_factory=lambda: ["all"],
        description="角色攻略提供方",
        json_schema_extra={"hint": "角色攻略图提供方"},
    )
    show_unowned_roles: bool = Field(
        default=True,
        description="显示未拥有角色",
        json_schema_extra={"hint": "是否在角色信息卡片中显示未拥有的角色和武器"},
    )
    allow_mention_query: bool = Field(
        default=True,
        description="允许AT查询他人",
        json_schema_extra={"hint": "是否允许通过 @ 查询他人的角色信息"},
    )

    @field_validator("command_prefixes", mode="before")
    @classmethod
    def _validate_prefixes(cls, v: Any) -> list[str]:
        # 前缀错误若回落为 kk 会改变命令触发面，必须让配置边界显式失败。
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v]
        raise ValueError("command_prefixes 必须是字符串或字符串列表")

    @property
    def command_prefix(self) -> str:
        """保持向前兼容的单前缀访问属性。"""
        return self.command_prefixes[0] if self.command_prefixes else "kk"


def migrate_config_dict(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """将老版 GsCore 嵌套配置、老版扁平配置或不完整配置迁移规范化为 typed 分组结构。"""
    result: dict[str, Any] = {
        "login": {},
        "network": {},
        "sign_in": {},
        "notifications": {},
        "display": {},
        "resources": {},
        "cache": {},
        "agent_tools": {},
    }
    if raw is None:
        return result

    raw_dict = dict(raw)

    known_sections = (
        "DNAUID配置",
        "DNAUID签到配置",
        "login",
        "network",
        "sign_in",
        "notifications",
        "display",
        "resources",
        "cache",
        "agent_tools",
    )
    for section_name in known_sections:
        # 已存在但结构错误的配置不是“缺省配置”，必须阻止迁移吞掉该错误。
        if section_name in raw_dict and not isinstance(raw_dict[section_name], Mapping):
            raise TypeError(f"配置分组 {section_name} 必须是对象")

    _log_discarded_mh_config(raw_dict)

    # 1. 检查并迁移 GScore 嵌套 section ("DNAUID配置", "DNAUID签到配置")
    for section_key in ("DNAUID配置", "DNAUID签到配置"):
        section_data = raw_dict.get(section_key)
        if isinstance(section_data, Mapping):
            for k, v in section_data.items():
                if k in _LEGACY_MAP:
                    group, field = _LEGACY_MAP[k]
                    if field == "command_prefixes" and isinstance(v, str):
                        result[group][field] = [v]
                    else:
                        result[group][field] = v

    # 2. 检查并迁移顶层扁平老字段
    for k, v in raw_dict.items():
        if k in _LEGACY_MAP:
            group, field = _LEGACY_MAP[k]
            if field == "command_prefixes" and isinstance(v, str):
                result[group][field] = [v]
            else:
                result[group][field] = v

    # 3. 合并已有的 typed 分组配置（typed 配置优先）
    for group_name in (
        "login",
        "network",
        "sign_in",
        "notifications",
        "display",
        "resources",
        "cache",
        "agent_tools",
    ):
        group_data = raw_dict.get(group_name)
        if isinstance(group_data, Mapping):
            for k, v in group_data.items():
                if group_name == "sign_in" and k in {
                    "game_enabled",
                    "community_enabled",
                }:
                    continue
                if group_name == "display" and k == "command_prefix":
                    if "command_prefixes" not in group_data:
                        result[group_name]["command_prefixes"] = v
                    continue
                if group_name == "notifications" and k in _REMOVED_MH_TYPED_FIELDS:
                    continue
                result[group_name][k] = v

    return result


class DnabySettings(_SettingsModel):
    """插件完整 typed 配置。"""

    login: LoginSettings = Field(default_factory=LoginSettings, description="登录设置")
    network: NetworkSettings = Field(
        default_factory=NetworkSettings, description="网络设置"
    )
    sign_in: SignInSettings = Field(
        default_factory=SignInSettings, description="签到设置"
    )
    notifications: NotificationSettings = Field(
        default_factory=NotificationSettings,
        description="通知设置",
    )
    display: DisplaySettings = Field(
        default_factory=DisplaySettings, description="显示设置"
    )
    resources: ResourceSettings = Field(
        default_factory=ResourceSettings, description="资源设置"
    )
    cache: CacheSettings = Field(
        default_factory=CacheSettings, description="缓存设置"
    )
    agent_tools: AgentToolsSettings = Field(
        default_factory=AgentToolsSettings,
        description="Agent Tools 设置",
    )

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> DnabySettings:
        """将 AstrBot 的嵌套配置字典转换为 typed settings。"""
        migrated = migrate_config_dict(config)
        settings = cls.model_validate(migrated)

        # 若传入的是可变字典（例如 AstrBotConfig），同步更新其标准分组键
        if isinstance(config, dict):
            _discard_removed_mh_config(config)
            for group_name, group_values in migrated.items():
                if group_name not in config or not isinstance(config[group_name], dict):
                    config[group_name] = dict(group_values)
                else:
                    config[group_name].update(group_values)

        if hasattr(DNAConfig, "bind"):
            DNAConfig.bind(dict(config) if config is not None else migrated)
        if hasattr(DNASignConfig, "bind"):
            DNASignConfig.bind(dict(config) if config is not None else migrated)
        return settings


def _log_discarded_mh_config(raw: Mapping[str, Any]) -> None:
    """记录旧版全局密函配置被丢弃，但不输出配置值。"""

    locations: list[tuple[str, str]] = []
    for key in _REMOVED_MH_LEGACY_KEYS:
        if key in raw:
            locations.append(("top-level", key))
    for section_name in ("DNAUID配置", "DNAUID签到配置"):
        section = raw.get(section_name)
        if isinstance(section, Mapping):
            for key in _REMOVED_MH_LEGACY_KEYS:
                if key in section:
                    locations.append((section_name, key))
    notifications = raw.get("notifications")
    if isinstance(notifications, Mapping):
        for field in _REMOVED_MH_TYPED_FIELDS:
            if field in notifications:
                locations.append(("notifications", field))
    for location, key in locations:
        logger.warning("[dnaby][config] 丢弃已移除的全局密函配置 %s.%s", location, key)


def _discard_removed_mh_config(raw: dict[str, Any]) -> None:
    """从 AstrBot 可变配置中移除已废弃密函全局键，避免再次持久化。"""

    for key in _REMOVED_MH_LEGACY_KEYS:
        raw.pop(key, None)
    for section_name in ("DNAUID配置", "DNAUID签到配置"):
        section = raw.get(section_name)
        if isinstance(section, dict):
            for key in _REMOVED_MH_LEGACY_KEYS:
                section.pop(key, None)
    notifications = raw.get("notifications")
    if isinstance(notifications, dict):
        for field in _REMOVED_MH_TYPED_FIELDS:
            notifications.pop(field, None)


__all__ = [
    "DNA_PREFIX",
    "AgentToolsSettings",
    "CacheSettings",
    "DNAConfig",
    "DNASignConfig",
    "DisplaySettings",
    "DnabySettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "ResourceSettings",
    "SignInSettings",
    "migrate_config_dict",
]
