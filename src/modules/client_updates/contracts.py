"""客户端更新领域的 typed contract 与公开 JSON 归一化边界。

本模块只处理公开更新接口的结构归一化，不创建 HTTP 请求，也不依赖 AstrBot
事件或运行期状态。原始 JSON 在进入领域层时必须经过这里的严格校验；未知的
直接总大小字段不会被读取。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast


_DECIMAL_KEY = re.compile(r"^[0-9]+$")


class ClientPlatform(StrEnum):
    """首版支持的国服客户端平台。"""

    PC = "pc"
    ANDROID = "android"


class ClientRegion(StrEnum):
    """首版固定支持的游戏区服。"""

    CN = "cn"


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


@dataclass(frozen=True, slots=True)
class ClientVersionSnapshot:
    """VersionList 中一个已归一化的最新版本快照。"""

    platform: ClientPlatform
    version_key: int
    patch_version: int
    resource_version_dir: str | None
    major: int
    minor: int
    revamp: int
    patch_key: int
    region: ClientRegion = ClientRegion.CN

    def __post_init__(self) -> None:
        """固定枚举和值对象字段，避免状态层保存歧义类型。"""

        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        object.__setattr__(self, "region", ClientRegion(self.region))
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
        if self.resource_version_dir is not None:
            if (
                not isinstance(self.resource_version_dir, str)
                or not self.resource_version_dir.strip()
            ):
                raise ValueError("resource_version_dir 必须是非空字符串")

    @property
    def version_text(self) -> str:
        """返回面向用户展示的四段版本号。"""

        return f"{self.major}.{self.minor}.{self.revamp}.{self.patch_key}"


# 后续状态/服务代码使用更短的领域名时，保留一个语义明确的别名。
ClientVersion = ClientVersionSnapshot


@dataclass(frozen=True, slots=True)
class ClientUpdateChange:
    """一次已确认的客户端版本变化及其新增字节数。"""

    previous: ClientVersionSnapshot
    current: ClientVersionSnapshot
    added_size_bytes: int
    region: ClientRegion = ClientRegion.CN
    platform: ClientPlatform = ClientPlatform.PC

    def __post_init__(self) -> None:
        """校验变化两端属于同一平台且确实向前推进。"""

        object.__setattr__(self, "region", ClientRegion(self.region))
        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        if not isinstance(self.previous, ClientVersionSnapshot):
            raise TypeError("previous 必须是 ClientVersionSnapshot")
        if not isinstance(self.current, ClientVersionSnapshot):
            raise TypeError("current 必须是 ClientVersionSnapshot")
        if (
            self.previous.region is not self.region
            or self.current.region is not self.region
        ):
            raise ValueError("变化快照的区服必须一致")
        if (
            self.previous.platform is not self.platform
            or self.current.platform is not self.platform
        ):
            raise ValueError("变化快照的平台必须一致")
        if self.current.patch_version <= self.previous.patch_version:
            raise ValueError("变化快照必须向前推进")
        if type(self.added_size_bytes) is not int or self.added_size_bytes < 0:
            raise ValueError("added_size_bytes 必须是非负整数")

    @property
    def event_key(self) -> str:
        """返回供投递去重使用的稳定变化键。"""

        return (
            f"{self.region.value}:{self.platform.value}:"
            f"{self.previous.patch_version}:{self.current.patch_version}"
        )


def parse_version_list(
    payload: object,
    platform: ClientPlatform | str,
) -> ClientVersionSnapshot:
    """校验并选择 VersionList 中数值上最新的一条版本记录。

    ``versionList`` 的 key 是字符串：PC 通常是 patchVersion，安卓通常同时
    充当资源目录号。因此排序始终使用归一化后的整数 ``version_key``，并以
    ``patch_version`` 作为同值时的稳定次序；安卓资源目录保留原始 key，不猜测
    或改写路径中的数字。
    """

    normalized_platform = _coerce_platform(platform)
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
                platform=normalized_platform,
                version_key=version_key,
                patch_version=_require_non_negative_int(
                    entry,
                    "patchVersion",
                    context=f"VersionList[{raw_key!r}]",
                ),
                resource_version_dir=(
                    raw_key if normalized_platform is ClientPlatform.ANDROID else None
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

    return max(
        versions, key=lambda version: (version.version_key, version.patch_version)
    )


def sum_patch_file_sizes(
    platform: ClientPlatform | str,
    pak_files_info: object,
    res_discrete_info: object,
) -> int:
    """归一化两类补丁清单并返回去重后的字节总数。

    两个清单均必须含有目标平台的 ``pakFileInfos`` 数组。文件名按原始非空
    字符串作为去重键，不做大小写、路径或版本号改写；相同文件名的大小冲突
    是结构错误而不是可合并数据。
    """

    normalized_platform = _coerce_platform(platform)
    platform_key = _manifest_platform_key(normalized_platform)
    sizes_by_name: dict[str, int] = {}

    for resource_name, payload in (
        ("PakFilesInfo", pak_files_info),
        ("ResDiscreteInfo", res_discrete_info),
    ):
        entries = _manifest_entries(payload, platform_key, resource_name)
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


def _manifest_platform_key(platform: ClientPlatform) -> str:
    if platform is ClientPlatform.PC:
        return "WindowsNoEditor"
    return "Android_ASTC"


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
    "ClientPlatform",
    "ClientRegion",
    "ClientUpdateChange",
    "ClientUpdateStructureError",
    "ClientVersion",
    "ClientVersionSnapshot",
    "parse_version_list",
    "sum_patch_file_sizes",
]
