"""v0.1 typed 配置定义。

配置模型只描述插件自己的领域配置，不依赖 AstrBot 的事件、命令或
``Context``。AstrBot 的嵌套字典在边界处通过 :meth:`DnabySettings.from_config`
转换为这些模型，避免业务代码继续直接操作未类型化的配置字典。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .legacy import DNA_PREFIX, DNAConfig, DNASignConfig


class _SettingsModel(BaseModel):
    """所有配置分组共用的校验策略。"""

    # 下方 port、并发和时间边界沿用 legacy 配置定义中已有的
    # max_value/平台端口范围；它们只拒绝越界配置，不截断输出、不增加重试或超时。
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LoginSettings(_SettingsModel):
    """登录接入和未登录账号容量配置。"""

    url: str = Field(
        default="",
        description="登录页或外置 dna-login 服务的 base URL；留空使用内置服务。",
    )
    bind_host: str = Field(
        default="127.0.0.1",
        description="内置登录服务监听地址。",
    )
    port: int = Field(
        default=6189,
        ge=0,
        le=65535,
        description="内置登录服务监听端口；0 表示由系统分配临时端口。",
    )
    transport: Literal["local", "http_poll", "sse", "ws"] = Field(
        default="local",
        description="登录接入方式。",
    )
    shared_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        description="外置登录服务共享密钥；不会写入日志或用户响应。",
    )
    tencent_docs: bool = Field(default=False, description="是否启用腾讯文档登录辅助。")
    qr_login: bool = Field(default=False, description="是否将登录链接转换为二维码。")
    forward_login: bool = Field(default=False, description="是否将登录链接转换为转发消息。")
    max_bind_count: int = Field(
        default=2,
        ge=0,
        le=100,
        description="未登录用户允许绑定的 UID 数量。",
    )


class NetworkSettings(_SettingsModel):
    """API、代理和 WebSocket 连接配置。"""

    api_proxy_url: str = Field(default="", description="二重螺旋 API 代理地址。")
    local_proxy_url: str = Field(default="", description="本地代理地址。")
    proxy_functions: list[Literal["all", "get_sms_code", "login"]] = Field(
        default_factory=list,
        description="需要使用代理的函数；空列表表示不额外指定。",
    )
    no_proxy_functions: list[str] = Field(
        default_factory=list,
        description="强制不使用代理的函数，优先级高于 proxy_functions。",
    )
    websocket_continue_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="WebSocket 保活持续时间（秒）。",
    )
    websocket_wait_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="等待 WebSocket 建立连接的时间（秒）。",
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
        description="启用的社区任务。",
    )
    enable_all_users: bool = Field(
        default=False,
        description="是否为所有已登录用户自动执行签到。",
    )
    scheduled_enabled: bool = Field(default=False, description="是否启用定时签到。")
    sign_time: str = Field(
        default="00:05",
        description="每日签到时间，格式为 HH:mm。",
    )

    @field_validator("sign_time", mode="before")
    @classmethod
    def _validate_sign_time(cls, value: Any) -> str:
        if isinstance(value, str):
            parts = value.strip().split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hour, minute = int(parts[0]), int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return f"{hour:02d}:{minute:02d}"
        elif isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                hour, minute = int(value[0]), int(value[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return f"{hour:02d}:{minute:02d}"
            except (ValueError, TypeError):
                pass
        return "00:05"
    concurrency: int = Field(
        default=1,
        ge=1,
        le=50,
        description="自动签到并发数量。",
    )
    concurrency_interval_seconds: tuple[int, int] = Field(
        default=(3, 5),
        description="自动签到任务之间的随机间隔范围（秒）。",
    )
    private_report: bool = Field(default=False, description="是否发送签到私聊报告。")
    group_report: bool = Field(default=False, description="是否发送签到群组报告。")
    group_report_image: bool = Field(default=False, description="是否以图片发送群组报告。")


class NotificationSettings(_SettingsModel):
    """公告和密函通知配置。"""

    announcement_enabled: bool = Field(default=True, description="是否启用公告推送。")
    announcement_groups: dict[str, Any] = Field(
        default_factory=dict,
        description="公告推送群组配置。",
    )
    announcement_ids: list[int] = Field(
        default_factory=list,
        description="已经推送过的公告 ID 列表。",
    )
    announcement_check_minutes: int = Field(
        default=10,
        ge=0,
        le=60,
        description="公告推送检查间隔（分钟）。",
    )
    secret_subscriptions: list[Literal["private", "group"]] = Field(
        default_factory=lambda: ["group"],
        description="密函订阅作用域。",
    )
    secret_push_time: str = Field(
        default="00:30",
        description="密函推送时间，格式为 分钟:秒。",
    )
    secret_cache: bool = Field(default=True, description="是否缓存密函数据。")
    secret_simple_image: bool = Field(default=False, description="是否使用简单密函图片。")


class DisplaySettings(_SettingsModel):
    """角色展示、攻略来源和 AT 查询配置。"""

    command_prefix: str = Field(
        default="kk",
        description="插件命令触发前缀，默认为 kk。",
    )
    guide_providers: list[Literal["all", "狩月庭攻略组", "猫冬"]] = Field(
        default_factory=lambda: ["all"],
        description="角色攻略图提供方。",
    )
    show_unowned_roles: bool = Field(
        default=True,
        description="是否在角色信息卡片中显示未拥有的角色和武器。",
    )
    allow_mention_query: bool = Field(
        default=True,
        description="是否允许通过 @ 查询他人的角色信息。",
    )


class DnabySettings(_SettingsModel):
    """插件完整 typed 配置。"""

    login: LoginSettings = Field(default_factory=LoginSettings, description="登录")
    network: NetworkSettings = Field(default_factory=NetworkSettings, description="网络")
    sign_in: SignInSettings = Field(default_factory=SignInSettings, description="签到")
    notifications: NotificationSettings = Field(
        default_factory=NotificationSettings,
        description="通知",
    )
    display: DisplaySettings = Field(default_factory=DisplaySettings, description="显示")

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> DnabySettings:
        """将 AstrBot 的嵌套配置字典转换为 typed settings。"""
        values = dict(config) if config is not None else {}
        sign_in = values.get("sign_in")
        if isinstance(sign_in, Mapping):
            # 旧版本的功能开关已废弃，只清理这两个已知字段；其余未知配置仍应显式报错。
            values["sign_in"] = {
                key: value
                for key, value in sign_in.items()
                if key not in {"game_enabled", "community_enabled"}
            }
        settings = cls.model_validate(values)
        if hasattr(DNAConfig, "bind"):
            DNAConfig.bind(values)
        if hasattr(DNASignConfig, "bind"):
            DNASignConfig.bind(values)
        return settings



__all__ = [
    "DNA_PREFIX",
    "DNAConfig",
    "DNASignConfig",
    "DisplaySettings",
    "DnabySettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "SignInSettings",
]
