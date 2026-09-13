"""客户端更新领域的 typed contract 与公开 JSON 归一化边界。

本模块只处理公开更新接口的结构归一化，不创建 HTTP 请求，也不依赖 AstrBot
事件或运行期状态。原始 JSON 在进入领域层时必须经过这里的严格校验；未知的
直接总大小字段不会被读取。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from ...entry.event import EventActor

_DECIMAL_KEY = re.compile(r"^[0-9]+$")


class ClientPlatform(StrEnum):
    """已验证客户端更新源使用的平台。"""

    PC = "pc"
    ANDROID = "android"
    IOS = "ios"


_CLIENT_UPDATE_PLATFORM_ORDER = (ClientPlatform.PC, ClientPlatform.ANDROID)
_LEGACY_CLIENT_UPDATE_PLATFORM_VALUES = frozenset(
    platform.value for platform in _CLIENT_UPDATE_PLATFORM_ORDER
)


def parse_legacy_client_update_platforms(
    extra_data: str,
) -> tuple[str, ...] | None:
    """解析旧订阅的平台元数据；无效形状返回 ``None``。"""

    try:
        payload = json.loads(extra_data)
    except (TypeError, json.JSONDecodeError):
        return None
    return _parse_legacy_client_update_platform_payload(payload)


def is_valid_client_update_subscription_metadata(extra_data: str) -> bool:
    """判断当前订阅元数据是否为中性空对象或合法旧平台形状。"""

    try:
        payload = json.loads(extra_data)
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        payload == {}
        or _parse_legacy_client_update_platform_payload(payload) is not None
    )


def _parse_legacy_client_update_platform_payload(
    payload: object,
) -> tuple[str, ...] | None:
    if not isinstance(payload, dict) or set(payload) != {"platforms"}:
        return None
    platforms = payload["platforms"]
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(not isinstance(platform, str) for platform in platforms)
    ):
        return None
    selected = set(platforms)
    if not selected.issubset(_LEGACY_CLIENT_UPDATE_PLATFORM_VALUES):
        return None
    return tuple(
        platform.value
        for platform in _CLIENT_UPDATE_PLATFORM_ORDER
        if platform.value in selected
    )


@dataclass(frozen=True, slots=True)
class ClientUpdateRequest:
    """不携带 Target selector 的客户端更新命令输入。"""

    actor: EventActor | None

    def __post_init__(self) -> None:
        if self.actor is not None and not isinstance(self.actor, EventActor):
            raise TypeError("actor 必须是 EventActor 或 None")


class ClientUpdateStructureError(ValueError):
    """公开更新 JSON 不符合契约时抛出的安全结构错误。

    ``detail`` 只供日志或测试诊断使用；异常字符串保持固定摘要，避免把原始
    服务端响应、文件名或 URL 意外带入用户可见消息。
    """

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("client update payload structure is invalid")

    def __repr__(self) -> str:
        """不把内部 detail 拼入 repr，避免异常被意外序列化。"""

        return "ClientUpdateStructureError()"


class ClientUpdateFailureKind(StrEnum):
    """客户端更新 transport 的可观察失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    CONTRACT = "contract"
    SERVER = "server"


class ClientUpdateTransportError(Exception):
    """不会把服务端原文、URL 或凭据带到用户响应的更新读取错误。"""

    def __init__(
        self,
        kind: ClientUpdateFailureKind | str,
        *,
        resource: str = "客户端更新数据",
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        self.kind = ClientUpdateFailureKind(kind)
        self.resource = resource
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"client update transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """异常 repr 只保留类别、固定资源名和状态码。"""

        return (
            "ClientUpdateTransportError("
            f"kind={self.kind.value!r}, resource={self.resource!r}, "
            f"status_code={self.status_code!r})"
        )


@dataclass(frozen=True, slots=True)
class ClientVersionSnapshot:
    """VersionList 中一条仅含 manifest provider 所需字段的记录。"""

    version_key: int
    patch_version: int
    resource_version_dir: str | None
    major: int
    minor: int
    revamp: int
    patch_key: int

    def __post_init__(self) -> None:
        """校验 manifest provider 所需的数值与目录字段。"""

        for field_name in (
            "version_key",
            "patch_version",
            "major",
            "minor",
            "revamp",
            "patch_key",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} 必须是非负整数")
        if self.resource_version_dir is not None and (
            not isinstance(self.resource_version_dir, str)
            or not self.resource_version_dir.strip()
        ):
            raise ValueError("resource_version_dir 必须是非空字符串")

    @property
    def version_text(self) -> str:
        """返回面向用户展示的四段版本号。"""

        return f"{self.major}.{self.minor}.{self.revamp}.{self.patch_key}"


ClientVersionOrderKey = int | str | tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ManifestCdnVersionMetadata:
    """manifest CDN 版本记录的 provider 专属元数据。"""

    version_key: int
    patch_version: int
    resource_version_dir: str | None

    def __post_init__(self) -> None:
        for field_name in ("version_key", "patch_version"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} 必须是非负整数")
        if self.resource_version_dir is not None and (
            not isinstance(self.resource_version_dir, str)
            or not self.resource_version_dir.strip()
        ):
            raise ValueError("resource_version_dir 必须是非空字符串或 None")


@dataclass(frozen=True, slots=True)
class AppStoreVersionMetadata:
    """App Store 当前版本的 provider 专属元数据。"""

    track_id: int
    country: str
    release_date: str | None = None

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
        if self.release_date is not None and (
            not isinstance(self.release_date, str) or not self.release_date.strip()
        ):
            raise ValueError("release_date 必须是非空字符串或 None")


ClientSourceProviderMetadata = ManifestCdnVersionMetadata | AppStoreVersionMetadata


@dataclass(frozen=True, slots=True)
class ClientSourceVersion:
    """一个不携带 Target 或发行渠道身份的 Source 版本。

    ``version_text`` 是可选的展示版本号；安装包型发行渠道（例如 B服 PC
    安装器、渠道 APK）不一定提供语义版本，变化判定只依赖 ``revision_id``。
    """

    source_id: str
    version_text: str | None
    revision_id: str
    order_key: ClientVersionOrderKey | None = None
    provider_metadata: ClientSourceProviderMetadata | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_id", "revision_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")
        if self.version_text is not None and (
            not isinstance(self.version_text, str) or not self.version_text.strip()
        ):
            raise ValueError("version_text 必须是非空字符串或 None")

        order_key = self.order_key
        if order_key is not None:
            if isinstance(order_key, bool) or not isinstance(
                order_key, (int, str, tuple)
            ):
                raise TypeError("order_key 必须是整数、字符串、整数元组或 None")
            if isinstance(order_key, int) and order_key < 0:
                raise ValueError("order_key 整数必须非负")
            if isinstance(order_key, str) and not order_key.strip():
                raise ValueError("order_key 字符串必须非空")
            if isinstance(order_key, tuple) and (
                not order_key
                or any(
                    isinstance(item, bool) or not isinstance(item, int) or item < 0
                    for item in order_key
                )
            ):
                raise ValueError("order_key 元组必须由非负整数组成")

        if self.provider_metadata is not None and not isinstance(
            self.provider_metadata,
            (ManifestCdnVersionMetadata, AppStoreVersionMetadata),
        ):
            raise TypeError("provider_metadata 必须是 typed provider metadata 或 None")


@dataclass(frozen=True, slots=True)
class ClientSourceObservation:
    """一次 Source 读取结果及其可见历史完整性。"""

    current: ClientSourceVersion
    observed_versions: tuple[ClientSourceVersion, ...]
    history_complete: bool
    added_size_bytes: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.current, ClientSourceVersion):
            raise TypeError("current 必须是 ClientSourceVersion")
        versions = tuple(self.observed_versions)
        if not versions or any(
            not isinstance(version, ClientSourceVersion) for version in versions
        ):
            raise ValueError("observed_versions 必须包含 ClientSourceVersion")
        if any(version.source_id != self.current.source_id for version in versions):
            raise ValueError("observation 中的版本必须属于同一 Source")
        if versions[-1] != self.current:
            raise ValueError("current 必须是 observed_versions 的最后一个版本")
        if type(self.history_complete) is not bool:
            raise TypeError("history_complete 必须是布尔值")
        if self.added_size_bytes is not None and (
            type(self.added_size_bytes) is not int or self.added_size_bytes < 0
        ):
            raise ValueError("added_size_bytes 必须是非负整数或 None")
        object.__setattr__(self, "observed_versions", versions)


class ClientUpdateTransport(Protocol):
    """客户端更新 use case 所需的 Source-neutral 读取 transport。"""

    async def get_observation(
        self,
        source_id: str,
        *,
        baseline: ClientSourceVersion | None = None,
    ) -> ClientSourceObservation:
        """读取一个已登记 Source 的当前版本和可见历史。"""
        ...


@dataclass(frozen=True, slots=True)
class ClientUpdateChange:
    """一次 Source 版本变化及事件创建时的 Target 快照。"""

    previous: ClientSourceVersion
    current: ClientSourceVersion
    history_complete: bool
    added_size_bytes: int | None
    target_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.previous, ClientSourceVersion):
            raise TypeError("previous 必须是 ClientSourceVersion")
        if not isinstance(self.current, ClientSourceVersion):
            raise TypeError("current 必须是 ClientSourceVersion")
        if self.previous.source_id != self.current.source_id:
            raise ValueError("变化两端必须属于同一 Source")
        if self.previous.revision_id == self.current.revision_id:
            raise ValueError("变化两端的 revision_id 必须不同")
        if type(self.history_complete) is not bool:
            raise TypeError("history_complete 必须是布尔值")
        if self.added_size_bytes is not None and (
            type(self.added_size_bytes) is not int or self.added_size_bytes < 0
        ):
            raise ValueError("added_size_bytes 必须是非负整数或 None")
        normalized_target_ids = tuple(self.target_ids)
        if not normalized_target_ids or any(
            not isinstance(target_id, str) or not target_id.strip()
            for target_id in normalized_target_ids
        ):
            raise ValueError("target_ids 必须包含非空 Target ID")
        if len(normalized_target_ids) != len(set(normalized_target_ids)):
            raise ValueError("target_ids 不能重复")
        object.__setattr__(self, "target_ids", normalized_target_ids)

    @property
    def source_id(self) -> str:
        """返回变化所属 Source。"""

        return self.current.source_id

    @property
    def event_key(self) -> str:
        """返回由 Source 和两端 revision 组成的稳定事件键。"""

        return (
            f"{self.source_id}:{self.previous.revision_id}:{self.current.revision_id}"
        )


def parse_version_list_entries(
    payload: object,
    platform: ClientPlatform | str,
) -> tuple[ClientVersionSnapshot, ...]:
    """按 manifest Source 平台解析 VersionList 的全部实际记录。"""

    return _parse_version_list_entries(
        payload,
        platform=_coerce_platform(platform),
    )


def _parse_version_list_entries(
    payload: object,
    *,
    platform: ClientPlatform,
) -> tuple[ClientVersionSnapshot, ...]:
    """严格解析 VersionList 中的全部版本条目。"""

    root = _require_mapping(payload, "VersionList")
    raw_versions = root.get("versionList")
    if not isinstance(raw_versions, Mapping) or not raw_versions:
        raise ClientUpdateStructureError(
            "VersionList.versionList must be a non-empty object"
        )

    versions: list[ClientVersionSnapshot] = []
    for raw_key, raw_entry in raw_versions.items():
        if not isinstance(raw_key, str) or _DECIMAL_KEY.fullmatch(raw_key) is None:
            raise ClientUpdateStructureError(
                "VersionList contains a non-numeric version key"
            )
        entry = _require_mapping(raw_entry, f"VersionList[{raw_key!r}]")
        version_key = int(raw_key)
        versions.append(
            ClientVersionSnapshot(
                version_key=version_key,
                patch_version=_require_non_negative_int(
                    entry,
                    "patchVersion",
                    context=f"VersionList[{raw_key!r}]",
                ),
                resource_version_dir=(
                    raw_key if platform is ClientPlatform.ANDROID else None
                ),
                major=_require_non_negative_int(
                    entry,
                    "major",
                    context=f"VersionList[{raw_key!r}]",
                ),
                minor=_require_non_negative_int(
                    entry,
                    "minor",
                    context=f"VersionList[{raw_key!r}]",
                ),
                revamp=_require_non_negative_int(
                    entry,
                    "revamp",
                    context=f"VersionList[{raw_key!r}]",
                ),
                patch_key=_require_non_negative_int(
                    entry,
                    "patchKey",
                    context=f"VersionList[{raw_key!r}]",
                ),
            )
        )

    return tuple(versions)


def sum_manifest_patch_file_sizes(
    pak_manifest_key: str,
    res_manifest_key: str,
    pak_files_info: object,
    res_discrete_info: object,
) -> int:
    """按两份 manifest 各自的 key 严格合并补丁清单。"""

    for field_name, value in (
        ("pak_manifest_key", pak_manifest_key),
        ("res_manifest_key", res_manifest_key),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} 必须是非空字符串")

    sizes_by_name: dict[str, int] = {}
    for resource_name, manifest_key, payload in (
        ("PakFilesInfo", pak_manifest_key, pak_files_info),
        ("ResDiscreteInfo", res_manifest_key, res_discrete_info),
    ):
        entries = _manifest_entries(payload, manifest_key, resource_name)
        for index, raw_entry in enumerate(entries):
            entry = _require_mapping(
                raw_entry, f"{resource_name}.pakFileInfos[{index}]"
            )
            file_name = entry.get("fileName")
            if not isinstance(file_name, str) or not file_name.strip():
                raise ClientUpdateStructureError(
                    f"{resource_name}.pakFileInfos[{index}].fileName must be non-empty"
                )
            file_size = entry.get("fileSize")
            if type(file_size) is not int or file_size < 0:
                raise ClientUpdateStructureError(
                    f"{resource_name}.pakFileInfos[{index}].fileSize must be a non-negative integer"
                )

            previous_size = sizes_by_name.get(file_name)
            if previous_size is not None and previous_size != file_size:
                raise ClientUpdateStructureError(
                    f"duplicate fileName has conflicting fileSize: {file_name!r}"
                )
            sizes_by_name.setdefault(file_name, file_size)

    return sum(sizes_by_name.values())


def _coerce_platform(platform: ClientPlatform | str) -> ClientPlatform:
    try:
        return ClientPlatform(platform)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"不支持的客户端平台: {platform!r}") from exc


def _require_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ClientUpdateStructureError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _require_non_negative_int(
    entry: Mapping[str, object],
    field_name: str,
    *,
    context: str,
) -> int:
    value = entry.get(field_name)
    if type(value) is not int or value < 0:
        raise ClientUpdateStructureError(
            f"{context}.{field_name} must be a non-negative integer"
        )
    return value


def _manifest_entries(
    payload: object,
    platform_key: str,
    resource_name: str,
) -> list[object]:
    root = _require_mapping(payload, resource_name)
    raw_map = root.get("pakFilesMap")
    if not isinstance(raw_map, Mapping):
        raise ClientUpdateStructureError(
            f"{resource_name}.pakFilesMap must be an object"
        )
    platform_payload = raw_map.get(platform_key)
    if not isinstance(platform_payload, Mapping):
        raise ClientUpdateStructureError(
            f"{resource_name}.pakFilesMap[{platform_key!r}] must be an object"
        )
    raw_entries = platform_payload.get("pakFileInfos")
    if not isinstance(raw_entries, list):
        raise ClientUpdateStructureError(
            f"{resource_name}.pakFilesMap[{platform_key!r}].pakFileInfos must be an array"
        )
    return raw_entries


__all__ = [
    "AppStoreVersionMetadata",
    "ClientPlatform",
    "ClientSourceObservation",
    "ClientSourceProviderMetadata",
    "ClientSourceVersion",
    "ClientUpdateChange",
    "ClientUpdateFailureKind",
    "ClientUpdateRequest",
    "ClientUpdateStructureError",
    "ClientUpdateTransport",
    "ClientUpdateTransportError",
    "ClientVersionOrderKey",
    "ClientVersionSnapshot",
    "ManifestCdnVersionMetadata",
    "parse_version_list_entries",
    "sum_manifest_patch_file_sizes",
]
