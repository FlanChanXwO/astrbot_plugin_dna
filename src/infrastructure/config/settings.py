"""v0.1 typed 配置定义。

配置模型只描述插件自己的领域配置，不依赖 AstrBot 的事件、命令或
``Context``。AstrBot 的嵌套字典在边界处通过 :meth:`DnabySettings.from_config`
转换为这些模型，避免业务代码继续直接操作未类型化的配置字典。
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
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
_REMOVED_CACHE_FIELDS = frozenset(
    (
        "fresh_ttl_minutes",
        "retention_ttl_hours",
        "announcement_ttl_hours",
    )
)


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


class GeneralSettings(_SettingsModel):
    """命令触发和跨功能查询行为配置。"""

    command_prefixes: list[str] = Field(
        default_factory=lambda: ["kk"],
        description="命令触发前缀列表",
        json_schema_extra={
            "hint": "插件支持的命令触发前缀列表，如 ['kk', 'dna']；列表含空字符串时允许无前缀触发"
        },
    )
    allow_mention_query: bool = Field(
        default=True,
        description="允许 AT 查询他人",
        json_schema_extra={"hint": "是否允许通过 @ 查询他人的角色信息"},
    )

    @field_validator("command_prefixes", mode="before")
    @classmethod
    def _validate_prefixes(cls, value: Any) -> list[str]:
        # 前缀错误若回落为 kk 会改变命令触发面，必须让配置边界显式失败。
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        raise ValueError("command_prefixes 必须是字符串或字符串列表")


class AISettings(_SettingsModel):
    """AI 相关能力开关。"""

    agent_tools_enabled: bool = Field(
        default=False,
        description="Agent Tools 总开关",
        json_schema_extra={"hint": "是否注册二重螺旋 Agent Tools"},
    )


class NetworkSettings(_SettingsModel):
    """二重螺旋 App API、代理和业务 WebSocket 配置。"""

    max_concurrent_requests: int = Field(
        default=4,
        ge=1,
        description="短请求最大并发数",
        json_schema_extra={
            "hint": "限制 API、图片等短生命周期网络请求；WebSocket/SSE 不长期占用",
        },
    )

    api_base_url: str = Field(
        default="",
        description="API 服务地址",
        json_schema_extra={"hint": "留空使用官方 API；仅在使用兼容 API 反代服务时填写"},
    )
    proxy_url: str = Field(
        default="",
        description="App API 代理地址",
        json_schema_extra={
            "hint": "仅代理二重螺旋 App REST API 与官方业务 WebSocket；留空直连，不影响 GitHub、CDN、AstrBot、OneBot 或外置登录"
        },
    )
    websocket_continue_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="API WebSocket 保活时间",
        json_schema_extra={
            "hint": "API WebSocket 保活持续时间（秒），不作用于 OneBot 或外置 dna-login WebSocket"
        },
    )
    websocket_wait_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="API WebSocket 连接等待时间",
        json_schema_extra={
            "hint": "等待 API WebSocket 建立连接的时间（秒），不作用于 OneBot 或外置 dna-login WebSocket"
        },
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
    """统一内容缓存的 TTL 配置。"""

    ttl_hours: int = Field(
        default=24,
        ge=-1,
        description="统一内容缓存 TTL（小时）",
        json_schema_extra={
            "hint": "-1 表示永久缓存；0 表示禁用持久缓存；正整数表示缓存有效小时数"
        },
    )
    refresh_send_card: bool = Field(
        default=True,
        description="刷新后发送角色面板",
        json_schema_extra={"hint": "主动刷新单个角色后是否发送新的角色面板图片"},
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
    default_auto_sign_enabled: bool = Field(
        default=True,
        description="首登自动签到",
        json_schema_extra={
            "hint": "新 UID 首次绑定时是否默认开启自动签到；用户之后可自行关闭"
        },
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

    @property
    def enable_all_users(self) -> bool:
        """兼容旧读取；真正的首登默认值由新字段表达。"""

        return self.default_auto_sign_enabled

    @property
    def scheduled_enabled(self) -> bool:
        """兼容旧 scheduler 读取；新的 scheduler 不再由配置开关门控。"""

        return True


class ClientUpdatesSettings(_SettingsModel):
    """客户端更新轮询、渠道和投递配置。"""

    enabled: bool = Field(
        default=True,
        description="客户端更新推送开关",
        json_schema_extra={"hint": "是否启用客户端更新定时检查与推送"},
    )
    check_minutes: int = Field(
        default=60,
        gt=0,
        description="客户端更新检查间隔",
        json_schema_extra={"hint": "客户端更新定时检查间隔（分钟），必须为正整数"},
    )
    channels: list[Literal["pc_cn", "android_astc_cn"]] = Field(
        default_factory=lambda: ["pc_cn", "android_astc_cn"],
        description="客户端更新渠道",
        json_schema_extra={
            "hint": "只能选择代码 registry 中的固定渠道 ID，不填写 URL、branch 或 manifest key"
        },
    )
    merge_forward: bool = Field(
        default=True,
        description="客户端更新合并转发",
        json_schema_extra={"hint": "OneBot 平台是否将同轮多渠道更新合并为转发消息"},
    )


class NotificationSettings(_SettingsModel):
    """公告和密函通知配置。"""

    _compat_client_update_enabled: bool = PrivateAttr(default=True)
    _compat_client_update_check_minutes: int = PrivateAttr(default=60)
    _compat_client_update_merge_forward: bool = PrivateAttr(default=True)

    def __init__(self, **data: Any) -> None:
        # 调度管理旧入口仍可能直接构造 NotificationSettings；兼容参数只在
        # 构造边界消费，不进入 typed model、model_dump 或 AstrBot schema。
        legacy_client_values = {
            key: data.pop(key)
            for key in (
                "client_update_enabled",
                "client_update_check_minutes",
                "client_update_merge_forward",
            )
            if key in data
        }
        super().__init__(**data)
        if legacy_client_values:
            client_updates = ClientUpdatesSettings.model_validate(
                {
                    "enabled": legacy_client_values.get(
                        "client_update_enabled",
                        self._compat_client_update_enabled,
                    ),
                    "check_minutes": legacy_client_values.get(
                        "client_update_check_minutes",
                        self._compat_client_update_check_minutes,
                    ),
                    "merge_forward": legacy_client_values.get(
                        "client_update_merge_forward",
                        self._compat_client_update_merge_forward,
                    ),
                }
            )
            self._set_client_update_compatibility(client_updates)

    announcement_enabled: bool = Field(
        default=True,
        description="公告推送开关",
        json_schema_extra={"hint": "是否启用公告推送"},
    )
    announcement_check_minutes: int = Field(
        default=10,
        ge=0,
        le=60,
        description="公告检查间隔",
        json_schema_extra={"hint": "公告推送检查间隔（分钟）"},
    )
    secret_simple_image: bool = Field(
        default=False,
        description="简易密函图片",
        json_schema_extra={"hint": "是否使用简单密函图片"},
    )
    secret_push_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="密函推送分钟",
        json_schema_extra={"hint": "每小时在该分钟推送密函，默认整点"},
    )
    secret_retry_interval_seconds: float = Field(
        default=1,
        gt=0,
        description="密函数据重试间隔",
        json_schema_extra={
            "hint": "当前小时密函未准备好或校验失败时的重试间隔（秒）",
            "invisible": True,
        },
    )

    def _set_client_update_compatibility(
        self,
        client_updates: ClientUpdatesSettings,
    ) -> None:
        self._compat_client_update_enabled = client_updates.enabled
        self._compat_client_update_check_minutes = client_updates.check_minutes
        self._compat_client_update_merge_forward = client_updates.merge_forward

    @property
    def client_update_enabled(self) -> bool:
        """兼容旧读取；正式配置位于 client_updates.enabled。"""

        return self._compat_client_update_enabled

    @property
    def client_update_check_minutes(self) -> int:
        """兼容旧读取；正式配置位于 client_updates.check_minutes。"""

        return self._compat_client_update_check_minutes

    @property
    def client_update_merge_forward(self) -> bool:
        """兼容旧读取；正式配置位于 client_updates.merge_forward。"""

        return self._compat_client_update_merge_forward


class DisplaySettings(_SettingsModel):
    """角色展示和攻略来源配置。"""

    _compat_command_prefixes: list[str] = PrivateAttr(default_factory=lambda: ["kk"])
    _compat_allow_mention_query: bool = PrivateAttr(default=True)

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

    def _set_general_compatibility(
        self,
        command_prefixes: list[str],
        allow_mention_query: bool,
    ) -> None:
        self._compat_command_prefixes = list(command_prefixes)
        self._compat_allow_mention_query = allow_mention_query

    @property
    def command_prefixes(self) -> list[str]:
        """兼容旧读取；正式配置位于 general.command_prefixes。"""

        return list(self._compat_command_prefixes)

    @property
    def command_prefix(self) -> str:
        """保持向前兼容的单前缀访问属性。"""

        return (
            self._compat_command_prefixes[0] if self._compat_command_prefixes else "kk"
        )

    @property
    def allow_mention_query(self) -> bool:
        """兼容旧读取；正式配置位于 general.allow_mention_query。"""

        return self._compat_allow_mention_query


_TARGET_CONFIG_GROUPS = (
    "general",
    "login",
    "ai",
    "sign_in",
    "notifications",
    "client_updates",
    "display",
    "network",
    "resources",
    "cache",
)
_REMOVED_SIGN_IN_FIELDS = frozenset(
    ("scheduled_enabled", "game_enabled", "community_enabled")
)
_REMOVED_NOTIFICATION_FIELDS = frozenset(
    (
        "announcement_ids",
        "secret_subscriptions",
        "client_update_enabled",
        "client_update_check_minutes",
        "client_update_merge_forward",
        "announcement_groups",
        *_REMOVED_MH_TYPED_FIELDS,
    )
)
_OLD_PROXY_COMPONENTS = frozenset(
    ("local_proxy_url", "proxy_functions", "no_proxy_functions")
)
_LEGACY_PROXY_COMPONENT_KEYS = {
    "LocalProxyUrl": "local_proxy_url",
    "NeedProxyFunc": "proxy_functions",
    "NoNeedProxyFunc": "no_proxy_functions",
}


def _normalize_migrated_value(field: str, value: Any) -> Any:
    if field == "command_prefixes" and isinstance(value, str):
        return [value]
    return copy.deepcopy(value)


def _record_assignment(
    result: dict[str, dict[str, Any]],
    assignments: dict[tuple[str, str], tuple[Any, str]],
    group: str,
    field: str,
    value: Any,
    source: str,
) -> None:
    normalized = _normalize_migrated_value(field, value)
    key = (group, field)
    previous = assignments.get(key)
    if previous is not None and previous[0] != normalized:
        raise ValueError(
            f"配置字段 {group}.{field} 存在冲突来源：{previous[1]} 与 {source}"
        )
    assignments[key] = (copy.deepcopy(normalized), source)
    result[group][field] = copy.deepcopy(normalized)


def _record_proxy_component(
    proxy_components: dict[str, tuple[Any, str]],
    field: str,
    value: Any,
    source: str,
) -> None:
    normalized = copy.deepcopy(value)
    previous = proxy_components.get(field)
    if previous is not None and previous[0] != normalized:
        raise ValueError(
            f"配置字段 network.{field} 存在冲突来源：{previous[1]} 与 {source}"
        )
    proxy_components[field] = (normalized, source)


def _discard_migrated_field(group: str, field: str, source: str) -> None:
    logger.warning(
        "[dnaby][config] 丢弃已移除配置 %s.%s（来源 %s）",
        group,
        field,
        source,
    )


def _consume_legacy_entry(
    result: dict[str, dict[str, Any]],
    assignments: dict[tuple[str, str], tuple[Any, str]],
    proxy_components: dict[str, tuple[Any, str]],
    key: str,
    value: Any,
    source: str,
) -> None:
    proxy_field = _LEGACY_PROXY_COMPONENT_KEYS.get(key, key)
    if proxy_field in _OLD_PROXY_COMPONENTS:
        _record_proxy_component(proxy_components, proxy_field, value, source)
        return
    mapped = _LEGACY_MAP.get(key)
    if mapped is None:
        return
    group, field = mapped
    if group == "notifications" and field in _REMOVED_NOTIFICATION_FIELDS:
        _discard_migrated_field(group, field, source)
        return
    if group == "sign_in" and field in _REMOVED_SIGN_IN_FIELDS:
        _discard_migrated_field(group, field, source)
        return
    _record_assignment(result, assignments, group, field, value, source)


def _consume_typed_group(
    result: dict[str, dict[str, Any]],
    assignments: dict[tuple[str, str], tuple[Any, str]],
    proxy_components: dict[str, tuple[Any, str]],
    group_name: str,
    group_data: Mapping[str, Any],
) -> None:
    for field, value in group_data.items():
        source = f"{group_name}.{field}"
        if group_name == "display":
            if field in {"command_prefix", "command_prefixes", "allow_mention_query"}:
                _record_assignment(
                    result,
                    assignments,
                    "general",
                    "command_prefixes" if field == "command_prefix" else field,
                    value,
                    source,
                )
            else:
                _record_assignment(result, assignments, "display", field, value, source)
            continue

        if group_name == "agent_tools":
            _record_assignment(
                result,
                assignments,
                "ai",
                "agent_tools_enabled" if field == "enabled" else field,
                value,
                source,
            )
            continue

        if group_name == "sign_in":
            if field in _REMOVED_SIGN_IN_FIELDS:
                _discard_migrated_field(group_name, field, source)
            elif field == "enable_all_users":
                _record_assignment(
                    result,
                    assignments,
                    "sign_in",
                    "default_auto_sign_enabled",
                    value,
                    source,
                )
            else:
                _record_assignment(result, assignments, "sign_in", field, value, source)
            continue

        if group_name == "notifications":
            if field in {
                "client_update_enabled",
                "client_update_check_minutes",
                "client_update_merge_forward",
            }:
                target_field = field.removeprefix("client_update_")
                _record_assignment(
                    result,
                    assignments,
                    "client_updates",
                    target_field,
                    value,
                    source,
                )
            elif field in _REMOVED_NOTIFICATION_FIELDS:
                _discard_migrated_field(group_name, field, source)
            else:
                _record_assignment(
                    result,
                    assignments,
                    "notifications",
                    field,
                    value,
                    source,
                )
            continue

        if group_name == "network":
            if field == "api_proxy_url":
                _record_assignment(
                    result,
                    assignments,
                    "network",
                    "api_base_url",
                    value,
                    source,
                )
            elif field in _OLD_PROXY_COMPONENTS:
                _record_proxy_component(proxy_components, field, value, source)
            else:
                _record_assignment(result, assignments, "network", field, value, source)
            continue

        if group_name == "cache" and field in _REMOVED_CACHE_FIELDS:
            _discard_migrated_field(group_name, field, source)
            continue
        _record_assignment(result, assignments, group_name, field, value, source)


def _resolve_legacy_proxy(
    result: dict[str, dict[str, Any]],
    assignments: dict[tuple[str, str], tuple[Any, str]],
    proxy_components: dict[str, tuple[Any, str]],
) -> None:
    if not proxy_components:
        return

    local_value = proxy_components.get("local_proxy_url", ("", "default"))[0]
    functions_value = proxy_components.get("proxy_functions", ([], "default"))[0]
    no_proxy_value = proxy_components.get("no_proxy_functions", ([], "default"))[0]

    if not isinstance(local_value, str):
        raise TypeError("旧版 local_proxy_url 必须是字符串")
    if not isinstance(functions_value, (list, tuple)):
        raise TypeError("旧版 proxy_functions 必须是字符串列表")
    if not isinstance(no_proxy_value, (list, tuple)):
        raise TypeError("旧版 no_proxy_functions 必须是字符串列表")
    if any(not isinstance(item, str) for item in functions_value):
        raise TypeError("旧版 proxy_functions 必须是字符串列表")
    if any(not isinstance(item, str) for item in no_proxy_value):
        raise TypeError("旧版 no_proxy_functions 必须是字符串列表")

    if (
        local_value.strip()
        and list(functions_value) == ["all"]
        and list(no_proxy_value) == []
    ):
        source = proxy_components.get("local_proxy_url", (None, "旧版局部代理"))[1]
        _record_assignment(
            result,
            assignments,
            "network",
            "proxy_url",
            local_value,
            f"{source}（完整旧局部代理）",
        )
        return

    if local_value.strip():
        logger.warning(
            "[dnaby][config] 检测到旧版按函数代理配置；该模式已废弃，为避免扩大代理范围，"
            "未自动迁移为统一代理，请重新配置 network.proxy_url"
        )


def migrate_config_dict(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """将旧配置迁移为目标分组，并在校验前显式处理冲突和废弃字段。"""
    result: dict[str, dict[str, Any]] = {
        group_name: {} for group_name in _TARGET_CONFIG_GROUPS
    }
    if raw is None:
        return result
    if not isinstance(raw, Mapping):
        raise TypeError("配置必须是对象")

    # 深拷贝只用于迁移快照；调用方传入的 AstrBot 配置永远不原地改写。
    raw_dict = copy.deepcopy(dict(raw))
    known_sections = (
        "DNAUID配置",
        "DNAUID签到配置",
        *_TARGET_CONFIG_GROUPS,
        "agent_tools",
    )
    for section_name in known_sections:
        if section_name in raw_dict and not isinstance(raw_dict[section_name], Mapping):
            raise TypeError(f"配置分组 {section_name} 必须是对象")

    _log_discarded_mh_config(raw_dict)
    _log_discarded_cache_config(raw_dict)

    assignments: dict[tuple[str, str], tuple[Any, str]] = {}
    proxy_components: dict[str, tuple[Any, str]] = {}

    for section_name in ("DNAUID配置", "DNAUID签到配置"):
        section_data = raw_dict.get(section_name)
        if isinstance(section_data, Mapping):
            for key, value in section_data.items():
                _consume_legacy_entry(
                    result,
                    assignments,
                    proxy_components,
                    str(key),
                    value,
                    f"{section_name}.{key}",
                )

    for key, value in raw_dict.items():
        if key in _LEGACY_MAP or key in _OLD_PROXY_COMPONENTS:
            _consume_legacy_entry(
                result,
                assignments,
                proxy_components,
                str(key),
                value,
                f"top-level.{key}",
            )

    for group_name in (*_TARGET_CONFIG_GROUPS, "agent_tools"):
        group_data = raw_dict.get(group_name)
        if isinstance(group_data, Mapping):
            _consume_typed_group(
                result,
                assignments,
                proxy_components,
                group_name,
                group_data,
            )

    _resolve_legacy_proxy(result, assignments, proxy_components)
    return result


class DnabySettings(_SettingsModel):
    """插件完整 typed 配置。"""

    general: GeneralSettings = Field(
        default_factory=GeneralSettings, description="通用设置"
    )
    login: LoginSettings = Field(default_factory=LoginSettings, description="登录设置")
    ai: AISettings = Field(default_factory=AISettings, description="AI 设置")
    sign_in: SignInSettings = Field(
        default_factory=SignInSettings, description="签到设置"
    )
    notifications: NotificationSettings = Field(
        default_factory=NotificationSettings,
        description="通知设置",
    )
    client_updates: ClientUpdatesSettings = Field(
        default_factory=ClientUpdatesSettings,
        description="客户端更新设置",
    )
    display: DisplaySettings = Field(
        default_factory=DisplaySettings, description="显示设置"
    )
    network: NetworkSettings = Field(
        default_factory=NetworkSettings, description="网络设置"
    )
    resources: ResourceSettings = Field(
        default_factory=ResourceSettings, description="资源设置"
    )
    cache: CacheSettings = Field(default_factory=CacheSettings, description="缓存设置")

    def model_post_init(self, __context: Any) -> None:
        """同步尚未迁移的旧读取属性，但不把兼容字段暴露为模型字段。"""
        self.display._set_general_compatibility(
            self.general.command_prefixes,
            self.general.allow_mention_query,
        )
        self.notifications._set_client_update_compatibility(self.client_updates)

    @property
    def agent_tools(self) -> AgentToolsSettings:
        """兼容旧读取；正式开关位于 ai.agent_tools_enabled。"""

        return AgentToolsSettings(enabled=self.ai.agent_tools_enabled)

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> DnabySettings:
        """将 AstrBot 的嵌套配置字典转换为 typed settings，且不改写输入。"""
        migrated = migrate_config_dict(config)
        settings = cls.model_validate(migrated)
        canonical_store = copy.deepcopy(migrated)

        if hasattr(DNAConfig, "bind"):
            DNAConfig.bind(copy.deepcopy(canonical_store))
        if hasattr(DNASignConfig, "bind"):
            DNASignConfig.bind(copy.deepcopy(canonical_store))
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


def _log_discarded_cache_config(raw: Mapping[str, Any]) -> None:
    """记录旧版缓存配置被丢弃，但不迁移旧的自定义数值。"""

    cache = raw.get("cache")
    if not isinstance(cache, Mapping):
        return
    for field in _REMOVED_CACHE_FIELDS:
        if field in cache:
            logger.warning(
                "[dnaby][config] 丢弃已移除的缓存配置 cache.%s",
                field,
            )


def _discard_removed_cache_config(raw: dict[str, Any]) -> None:
    """从 AstrBot 可变配置中移除旧缓存字段，避免再次持久化。"""

    cache = raw.get("cache")
    if isinstance(cache, dict):
        for field in _REMOVED_CACHE_FIELDS:
            cache.pop(field, None)


__all__ = [
    "DNA_PREFIX",
    "AISettings",
    "AgentToolsSettings",
    "CacheSettings",
    "ClientUpdatesSettings",
    "DNAConfig",
    "DNASignConfig",
    "DisplaySettings",
    "DnabySettings",
    "GeneralSettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "ResourceSettings",
    "SignInSettings",
    "migrate_config_dict",
]
