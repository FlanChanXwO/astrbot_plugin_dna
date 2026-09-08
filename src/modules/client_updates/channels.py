"""客户端更新固定渠道 registry。

渠道 ID 是配置和状态边界使用的稳定标识；主机、分支、manifest key 和
User-Agent 等协议细节只在本模块集中声明，调用方不得自行拼接一套渠道配置。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .contracts import ClientPlatform, ClientRegion


@dataclass(frozen=True, slots=True)
class ClientUpdateChannel:
    """一个固定客户端更新渠道的协议元数据。"""

    channel_id: str
    name: str
    region: ClientRegion
    platform: ClientPlatform
    primary_base_url: str
    fallback_base_url: str
    branch: str
    manifest_key: str
    user_agent: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "region", ClientRegion(self.region))
        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        for field_name in (
            "channel_id",
            "name",
            "primary_base_url",
            "fallback_base_url",
            "branch",
            "manifest_key",
            "user_agent",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")


CLIENT_UPDATE_CHANNELS: Mapping[str, ClientUpdateChannel] = MappingProxyType(
    {
        "pc_cn": ClientUpdateChannel(
            channel_id="pc_cn",
            name="国服 PC",
            region=ClientRegion.CN,
            platform=ClientPlatform.PC,
            primary_base_url="http://pan01-1-eo.shyxhy.com",
            fallback_base_url="http://pan01-1-hs.shyxhy.com",
            branch="Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub",
            manifest_key="WindowsNoEditor",
            user_agent=(
                "EMLauncher/++UE4+Release-4.27-CL-0 Windows/10.0.26100.1.256.64bit"
            ),
        ),
        "android_astc_cn": ClientUpdateChannel(
            channel_id="android_astc_cn",
            name="国服安卓 ASTC",
            region=ClientRegion.CN,
            platform=ClientPlatform.ANDROID,
            primary_base_url="https://pan01-1-hs.shyxhy.com",
            fallback_base_url="http://pan01-1-eo.shyxhy.com",
            branch="Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub",
            manifest_key="Android_ASTC",
            user_agent="EM/++UE4+Release-4.27-CL-0 Android/12",
        ),
    }
)

# 旧 platform API 仍需有确定的默认渠道；新代码应使用 channel ID。
_DEFAULT_CHANNEL_BY_PLATFORM: Mapping[ClientPlatform, str] = MappingProxyType(
    {
        ClientPlatform.PC: "pc_cn",
        ClientPlatform.ANDROID: "android_astc_cn",
    }
)

# 兼容外部调用方可能使用的 registry 别名；实际数据仍只有一份。
CHANNEL_REGISTRY = CLIENT_UPDATE_CHANNELS


def resolve_client_update_channel(
    channel_id: str | ClientUpdateChannel,
) -> ClientUpdateChannel:
    """按固定 ID 返回渠道；URL、platform 值和未知字符串都会显式失败。"""

    if isinstance(channel_id, ClientUpdateChannel):
        return channel_id
    if not isinstance(channel_id, str):
        raise TypeError("客户端更新渠道 ID 必须是字符串")
    try:
        return CLIENT_UPDATE_CHANNELS[channel_id]
    except KeyError as error:
        raise ValueError("不支持的客户端更新渠道") from error


def default_channel_id_for_platform(platform: ClientPlatform | str) -> str:
    """返回旧平台 API 对应的固定默认渠道 ID。"""

    try:
        normalized = ClientPlatform(platform)
        return _DEFAULT_CHANNEL_BY_PLATFORM[normalized]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("不支持的客户端平台") from error


def normalize_client_update_channel_ids(channels: object) -> tuple[str, ...]:
    """校验并归一化配置中的固定渠道 ID，保留用户选择顺序且去重。"""

    if isinstance(channels, str):
        raise TypeError("客户端更新渠道必须是 channel ID 序列")

    try:
        candidates = tuple(channels)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError("客户端更新渠道必须是可迭代值") from error

    normalized: list[str] = []
    for candidate in candidates:
        channel = resolve_client_update_channel(candidate)
        if channel.channel_id not in normalized:
            normalized.append(channel.channel_id)
    return tuple(normalized)


def select_enabled_channels(
    channel_ids: object,
    *,
    platform: ClientPlatform | str | None,
) -> tuple[str, ...]:
    """从已启用渠道中筛选一个平台；``None`` 返回全部已启用渠道。"""

    normalized = normalize_client_update_channel_ids(channel_ids)
    if platform is None:
        return normalized
    normalized_platform = ClientPlatform(platform)
    return tuple(
        channel_id
        for channel_id in normalized
        if CLIENT_UPDATE_CHANNELS[channel_id].platform is normalized_platform
    )


__all__ = [
    "CHANNEL_REGISTRY",
    "CLIENT_UPDATE_CHANNELS",
    "ClientUpdateChannel",
    "default_channel_id_for_platform",
    "normalize_client_update_channel_ids",
    "resolve_client_update_channel",
    "select_enabled_channels",
]
