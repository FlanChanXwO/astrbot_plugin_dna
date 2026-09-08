"""客户端更新 Target / Source registry。

这里只登记已经过只读上游核验的组合。下载入口或候选区服不能在缺少稳定
版本 Source 时进入 registry。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from .contracts import ClientPlatform


class ClientUpdateProviderKind(StrEnum):
    """Source 使用的版本读取协议。"""

    MANIFEST_CDN = "manifest_cdn"
    APP_STORE = "app_store"


@dataclass(frozen=True, slots=True)
class ManifestCdnProviderConfig:
    """VersionList + manifest CDN 的固定协议参数。"""

    primary_base_url: str
    fallback_base_url: str
    branch: str
    pak_manifest_key: str
    res_manifest_key: str
    user_agent: str

    def __post_init__(self) -> None:
        for field_name in (
            "primary_base_url",
            "fallback_base_url",
            "branch",
            "pak_manifest_key",
            "res_manifest_key",
            "user_agent",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")


@dataclass(frozen=True, slots=True)
class AppStoreProviderConfig:
    """Apple Lookup 当前版本查询参数。"""

    track_id: int
    country: str

    def __post_init__(self) -> None:
        if type(self.track_id) is not int or self.track_id <= 0:
            raise ValueError("track_id 必须是正整数")
        if (
            not isinstance(self.country, str)
            or len(self.country) != 2
            or not self.country.isascii()
            or not self.country.isalpha()
        ):
            raise ValueError("country 必须是两个 ASCII 字母")
        object.__setattr__(self, "country", self.country.lower())


ClientUpdateProviderConfig = ManifestCdnProviderConfig | AppStoreProviderConfig


@dataclass(frozen=True, slots=True)
class ClientUpdateSource:
    """可被多个 Target 复用的技术版本来源。"""

    source_id: str
    platform: ClientPlatform
    provider_kind: ClientUpdateProviderKind
    provider_config: ClientUpdateProviderConfig

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id 必须是非空字符串")
        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        object.__setattr__(
            self,
            "provider_kind",
            ClientUpdateProviderKind(self.provider_kind),
        )
        expected_config_type = {
            ClientUpdateProviderKind.MANIFEST_CDN: ManifestCdnProviderConfig,
            ClientUpdateProviderKind.APP_STORE: AppStoreProviderConfig,
        }[self.provider_kind]
        if not isinstance(self.provider_config, expected_config_type):
            raise TypeError("provider_kind 与 provider_config 不匹配")
        if (
            self.provider_kind is ClientUpdateProviderKind.APP_STORE
            and self.platform is not ClientPlatform.IOS
        ):
            raise ValueError("app_store Source 平台必须是 iOS")
        if (
            self.provider_kind is ClientUpdateProviderKind.MANIFEST_CDN
            and self.platform is ClientPlatform.IOS
        ):
            raise ValueError("iOS Source 不能伪装成 manifest_cdn")


@dataclass(frozen=True, slots=True)
class ClientUpdateTarget:
    """用户可见的区服、账号生态和平台组合。"""

    target_id: str
    region_id: str
    ecosystem_id: str
    platform: ClientPlatform
    source_id: str
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        for field_name in (
            "target_id",
            "region_id",
            "ecosystem_id",
            "source_id",
            "display_name",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")


@dataclass(frozen=True, slots=True)
class ClientUpdateRegistry:
    """校验并索引一组 Target / Source。"""

    sources: tuple[ClientUpdateSource, ...]
    targets: tuple[ClientUpdateTarget, ...]
    _sources_by_id: Mapping[str, ClientUpdateSource] = field(init=False, repr=False)
    _targets_by_id: Mapping[str, ClientUpdateTarget] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        targets = tuple(self.targets)
        if any(not isinstance(source, ClientUpdateSource) for source in sources):
            raise TypeError("sources 必须全部是 ClientUpdateSource")
        if any(not isinstance(target, ClientUpdateTarget) for target in targets):
            raise TypeError("targets 必须全部是 ClientUpdateTarget")

        sources_by_id: dict[str, ClientUpdateSource] = {}
        for source in sources:
            if source.source_id in sources_by_id:
                raise ValueError(f"Source ID 重复: {source.source_id}")
            sources_by_id[source.source_id] = source

        targets_by_id: dict[str, ClientUpdateTarget] = {}
        identities: set[tuple[str, str, ClientPlatform]] = set()
        display_names: set[str] = set()
        for target in targets:
            if target.target_id in targets_by_id:
                raise ValueError(f"Target ID 重复: {target.target_id}")
            identity = (target.region_id, target.ecosystem_id, target.platform)
            if identity in identities:
                raise ValueError("Target 组合重复")
            if target.display_name in display_names:
                raise ValueError("Target 展示名重复")
            source = sources_by_id.get(target.source_id)
            if source is None:
                raise ValueError(f"Target 引用了不存在的 Source: {target.source_id}")
            if source.platform is not target.platform:
                raise ValueError("Target 与 Source 平台不一致")
            identities.add(identity)
            display_names.add(target.display_name)
            targets_by_id[target.target_id] = target

        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "_sources_by_id", MappingProxyType(sources_by_id))
        object.__setattr__(self, "_targets_by_id", MappingProxyType(targets_by_id))

    @property
    def sources_by_id(self) -> Mapping[str, ClientUpdateSource]:
        return self._sources_by_id

    @property
    def targets_by_id(self) -> Mapping[str, ClientUpdateTarget]:
        return self._targets_by_id

    def resolve_source(self, source_id: str | ClientUpdateSource) -> ClientUpdateSource:
        candidate = source_id if isinstance(source_id, ClientUpdateSource) else None
        lookup_id = candidate.source_id if candidate is not None else source_id
        if not isinstance(lookup_id, str):
            raise TypeError("客户端更新 Source ID 必须是字符串")
        try:
            registered = self._sources_by_id[lookup_id]
        except KeyError as error:
            raise ValueError("不支持的客户端更新 Source") from error
        if candidate is not None and candidate != registered:
            raise ValueError("客户端更新 Source 与 registry 登记不一致")
        return registered

    def resolve_target(self, target_id: str | ClientUpdateTarget) -> ClientUpdateTarget:
        candidate = target_id if isinstance(target_id, ClientUpdateTarget) else None
        lookup_id = candidate.target_id if candidate is not None else target_id
        if not isinstance(lookup_id, str):
            raise TypeError("客户端更新 Target ID 必须是字符串")
        try:
            registered = self._targets_by_id[lookup_id]
        except KeyError as error:
            raise ValueError("不支持的客户端更新 Target") from error
        if candidate is not None and candidate != registered:
            raise ValueError("客户端更新 Target 与 registry 登记不一致")
        return registered

    def normalize_target_ids(self, target_ids: object) -> tuple[str, ...]:
        if isinstance(target_ids, str):
            raise TypeError("客户端更新 Target 必须是 Target ID 序列")
        try:
            candidates = tuple(target_ids)  # type: ignore[arg-type]
        except TypeError as error:
            raise ValueError("客户端更新 Target 必须是可迭代值") from error

        normalized: list[str] = []
        for candidate in candidates:
            target_id = self.resolve_target(candidate).target_id
            if target_id not in normalized:
                normalized.append(target_id)
        return tuple(normalized)

    def group_target_ids_by_source(
        self,
        target_ids: object,
    ) -> Mapping[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for target_id in self.normalize_target_ids(target_ids):
            source_id = self._targets_by_id[target_id].source_id
            grouped.setdefault(source_id, []).append(target_id)
        return MappingProxyType(
            {source_id: tuple(ids) for source_id, ids in grouped.items()}
        )

    def select_target_ids_by_platform(
        self,
        target_ids: object,
        platform: ClientPlatform | str,
    ) -> tuple[str, ...]:
        normalized_platform = ClientPlatform(platform)
        return tuple(
            target_id
            for target_id in self.normalize_target_ids(target_ids)
            if self._targets_by_id[target_id].platform is normalized_platform
        )


_CLIENT_UPDATE_REGISTRY = ClientUpdateRegistry(
    sources=(
        ClientUpdateSource(
            source_id="cn-official-pc-manifest",
            platform=ClientPlatform.PC,
            provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
            provider_config=ManifestCdnProviderConfig(
                primary_base_url="http://pan01-1-eo.shyxhy.com",
                fallback_base_url="http://pan01-1-hs.shyxhy.com",
                branch=(
                    "Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub"
                ),
                pak_manifest_key="WindowsNoEditor",
                res_manifest_key="WindowsNoEditor",
                user_agent=(
                    "EMLauncher/++UE4+Release-4.27-CL-0 "
                    "Windows/10.0.26100.1.256.64bit"
                ),
            ),
        ),
        ClientUpdateSource(
            source_id="cn-official-android-astc-manifest",
            platform=ClientPlatform.ANDROID,
            provider_kind=ClientUpdateProviderKind.MANIFEST_CDN,
            provider_config=ManifestCdnProviderConfig(
                primary_base_url="https://pan01-1-hs.shyxhy.com",
                fallback_base_url="http://pan01-1-eo.shyxhy.com",
                branch="Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub",
                pak_manifest_key="Android_ASTC",
                res_manifest_key="WindowsNoEditor",
                user_agent="EM/++UE4+Release-4.27-CL-0 Android/12",
            ),
        ),
        ClientUpdateSource(
            source_id="cn-official-ios-app-store",
            platform=ClientPlatform.IOS,
            provider_kind=ClientUpdateProviderKind.APP_STORE,
            provider_config=AppStoreProviderConfig(track_id=6470771372, country="cn"),
        ),
    ),
    targets=(
        ClientUpdateTarget(
            target_id="cn-official-pc",
            region_id="cn",
            ecosystem_id="official",
            platform=ClientPlatform.PC,
            source_id="cn-official-pc-manifest",
            display_name="国服官服 PC",
        ),
        ClientUpdateTarget(
            target_id="cn-official-android",
            region_id="cn",
            ecosystem_id="official",
            platform=ClientPlatform.ANDROID,
            source_id="cn-official-android-astc-manifest",
            display_name="国服官服 Android",
        ),
        ClientUpdateTarget(
            target_id="cn-official-ios",
            region_id="cn",
            ecosystem_id="official",
            platform=ClientPlatform.IOS,
            source_id="cn-official-ios-app-store",
            display_name="国服官服 iOS",
        ),
    ),
)

CLIENT_UPDATE_SOURCES = _CLIENT_UPDATE_REGISTRY.sources_by_id
CLIENT_UPDATE_TARGETS = _CLIENT_UPDATE_REGISTRY.targets_by_id
DEFAULT_CLIENT_UPDATE_TARGET_IDS = (
    "cn-official-pc",
    "cn-official-android",
)


def resolve_client_update_source(
    source_id: str | ClientUpdateSource,
) -> ClientUpdateSource:
    return _CLIENT_UPDATE_REGISTRY.resolve_source(source_id)


def resolve_client_update_target(
    target_id: str | ClientUpdateTarget,
) -> ClientUpdateTarget:
    return _CLIENT_UPDATE_REGISTRY.resolve_target(target_id)


def normalize_client_update_target_ids(target_ids: object) -> tuple[str, ...]:
    return _CLIENT_UPDATE_REGISTRY.normalize_target_ids(target_ids)


def group_client_update_target_ids_by_source(
    target_ids: object,
) -> Mapping[str, tuple[str, ...]]:
    return _CLIENT_UPDATE_REGISTRY.group_target_ids_by_source(target_ids)


def select_client_update_target_ids_by_platform(
    target_ids: object,
    platform: ClientPlatform | str,
) -> tuple[str, ...]:
    return _CLIENT_UPDATE_REGISTRY.select_target_ids_by_platform(target_ids, platform)


__all__ = [
    "CLIENT_UPDATE_SOURCES",
    "CLIENT_UPDATE_TARGETS",
    "DEFAULT_CLIENT_UPDATE_TARGET_IDS",
    "AppStoreProviderConfig",
    "ClientUpdateProviderConfig",
    "ClientUpdateProviderKind",
    "ClientUpdateRegistry",
    "ClientUpdateSource",
    "ClientUpdateTarget",
    "ManifestCdnProviderConfig",
    "group_client_update_target_ids_by_source",
    "normalize_client_update_target_ids",
    "resolve_client_update_source",
    "resolve_client_update_target",
    "select_client_update_target_ids_by_platform",
]
