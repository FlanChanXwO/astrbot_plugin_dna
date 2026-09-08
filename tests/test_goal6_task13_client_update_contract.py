"""Goal 6 T13：platform/channel 分离与客户端更新协议的 Red 契约。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from src.infrastructure.config.schema import generate_astrbot_schema
from src.infrastructure.config.settings import DnabySettings
from src.modules import client_updates
from src.modules.client_updates import messages
from src.modules.client_updates.contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateStructureError,
    ClientVersionSnapshot,
)

PC_MAIN = "http://pan01-1-eo.shyxhy.com"
PC_FALLBACK = "http://pan01-1-hs.shyxhy.com"
ANDROID_MAIN = "https://pan01-1-hs.shyxhy.com"
ANDROID_FALLBACK = PC_MAIN
PC_BRANCH = "Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub"
ANDROID_BRANCH = "Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub"
PC_USER_AGENT = "EMLauncher/++UE4+Release-4.27-CL-0 Windows/10.0.26100.1.256.64bit"
ANDROID_USER_AGENT = "EM/++UE4+Release-4.27-CL-0 Android/12"


def _required(name: str) -> Any:
    value = getattr(client_updates, name, None)
    assert value is not None, f"客户端更新公开契约缺少 {name}"
    return value


def _field(spec: object, name: str) -> object:
    if isinstance(spec, Mapping):
        return spec[name]
    return getattr(spec, name)


def _version_entry(
    patch_version: int,
    *,
    revamp: int,
    patch_key: int = 1,
) -> dict[str, int]:
    return {
        "major": 1,
        "minor": 5,
        "revamp": revamp,
        "patchKey": patch_key,
        "patchVersion": patch_version,
    }


def _version_list(entries: Mapping[str, Mapping[str, int]]) -> dict[str, object]:
    return {"versionList": dict(entries)}


def _manifest(
    entries_by_manifest_key: Mapping[str, list[dict[str, object]]],
    *,
    direct_size: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "pakFilesMap": {
            manifest_key: {"pakFileInfos": entries}
            for manifest_key, entries in entries_by_manifest_key.items()
        }
    }
    if direct_size is not None:
        payload["updateSize"] = direct_size
    return payload


def _snapshot(
    channel_id: str,
    patch_version: int,
    *,
    platform: ClientPlatform = ClientPlatform.PC,
) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
        channel_id=channel_id,
        platform=platform,
        region=ClientRegion.CN,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=(
            str(patch_version) if platform is ClientPlatform.ANDROID else None
        ),
        major=1,
        minor=5,
        revamp=192,
        patch_key=patch_version,
    )


def test_fixed_channel_registry_keeps_protocol_metadata_in_code() -> None:
    """固定 registry 必须同时表达 ID、平台、源、分支和 manifest key。"""

    registry = _required("CLIENT_UPDATE_CHANNELS")
    assert isinstance(registry, Mapping)
    assert {"pc_cn", "android_astc_cn"}.issubset(registry)

    expected = {
        "pc_cn": {
            "region": ClientRegion.CN,
            "platform": ClientPlatform.PC,
            "primary_base_url": PC_MAIN,
            "fallback_base_url": PC_FALLBACK,
            "branch": PC_BRANCH,
            "manifest_key": "WindowsNoEditor",
            "user_agent": PC_USER_AGENT,
        },
        "android_astc_cn": {
            "region": ClientRegion.CN,
            "platform": ClientPlatform.ANDROID,
            "primary_base_url": ANDROID_MAIN,
            "fallback_base_url": ANDROID_FALLBACK,
            "branch": ANDROID_BRANCH,
            "manifest_key": "Android_ASTC",
            "user_agent": ANDROID_USER_AGENT,
        },
    }

    for channel_id, fields in expected.items():
        spec = registry[channel_id]
        assert _field(spec, "channel_id") == channel_id
        for field_name, value in fields.items():
            assert _field(spec, field_name) == value
        assert _field(spec, "name")


def test_client_update_config_options_are_derived_from_registry_ids_only() -> None:
    """配置只接受 registry ID，不能把 URL、branch 或 manifest 细节写入配置。"""

    registry = _required("CLIENT_UPDATE_CHANNELS")
    channel_ids = list(registry)
    settings = DnabySettings.from_config({"client_updates": {"channels": channel_ids}})
    assert settings.client_updates.channels == channel_ids

    schema = generate_astrbot_schema()
    options = schema["client_updates"]["items"]["channels"]["options"]
    assert set(options) == set(channel_ids)

    with pytest.raises(ValidationError):
        DnabySettings.from_config(
            {
                "client_updates": {
                    "channels": [
                        {
                            "channel_id": channel_ids[0],
                            "branch": "caller-controlled-branch",
                        }
                    ]
                }
            }
        )


def test_unknown_channel_id_is_rejected_instead_of_being_treated_as_platform_or_url() -> (
    None
):
    """未知 ID 必须显式失败，不得回退为自由 URL 或 pc/android 平台。"""

    resolver = _required("resolve_client_update_channel")
    with pytest.raises((KeyError, ValueError, ClientUpdateStructureError)):
        resolver("https://attacker.example/update.json")
    with pytest.raises((KeyError, ValueError, ClientUpdateStructureError)):
        resolver("pc")
    with pytest.raises((KeyError, ValueError, ClientUpdateStructureError)):
        resolver("not-registered")


def test_commands_filter_enabled_channel_ids_by_platform() -> None:
    """平台命令只能筛选 enabled channel，不能把一个 platform 当成一个 channel。"""

    selector = _required("select_enabled_channels")
    enabled = ("pc_cn", "android_astc_cn")
    assert selector(enabled, platform=ClientPlatform.PC) == ("pc_cn",)
    assert selector(enabled, platform=ClientPlatform.ANDROID) == ("android_astc_cn",)
    assert selector(enabled, platform=None) == enabled


def test_version_list_snapshot_retains_channel_and_same_entry_fields() -> None:
    """VersionList 的展示字段、patchVersion 和 channel 身份必须来自同一条记录。"""

    parser = _required("parse_channel_version_list")
    payload = _version_list(
        {
            "1010164": _version_entry(200, revamp=192, patch_key=3),
            "1010165": _version_entry(201, revamp=193, patch_key=4),
        }
    )

    snapshot = parser(payload, channel_id="android_astc_cn")
    assert snapshot.channel_id == "android_astc_cn"
    assert snapshot.region is ClientRegion.CN
    assert snapshot.platform is ClientPlatform.ANDROID
    assert snapshot.version_key == 1010165
    assert snapshot.patch_version == 201
    assert snapshot.resource_version_dir == "1010165"
    assert snapshot.version_text == "1.5.193.4"


def test_manifest_key_and_patch_size_are_selected_by_channel() -> None:
    """同一批 manifest 可含多个平台，大小计算必须由 channel 的 manifest key 决定。"""

    size_parser = _required("sum_channel_patch_file_sizes")
    pak = _manifest(
        {
            "WindowsNoEditor": [{"fileName": "pc.pak", "fileSize": 3}],
            "Android_ASTC": [{"fileName": "android.chunk", "fileSize": 4}],
        },
        direct_size=999999,
    )
    res = _manifest(
        {
            "WindowsNoEditor": [{"fileName": "pc-res.pak", "fileSize": 2}],
            "Android_ASTC": [{"fileName": "android-res.chunk", "fileSize": 3}],
        }
    )

    assert size_parser("pc_cn", pak, res) == 5
    assert size_parser("android_astc_cn", pak, res) == 7


def test_same_platform_channel_changes_have_distinct_event_keys() -> None:
    """同一 platform 的不同 channel 不能共享 baseline 或 pending event 身份。"""

    pc_cn_previous = _snapshot("pc_cn", 100)
    pc_cn_current = _snapshot("pc_cn", 101)
    pc_test_previous = _snapshot("pc_test_cn", 100)
    pc_test_current = _snapshot("pc_test_cn", 101)

    first = ClientUpdateChange(
        channel_id="pc_cn",
        previous=pc_cn_previous,
        current=pc_cn_current,
        added_size_bytes=10,
        region=ClientRegion.CN,
        platform=ClientPlatform.PC,
    )
    second = ClientUpdateChange(
        channel_id="pc_test_cn",
        previous=pc_test_previous,
        current=pc_test_current,
        added_size_bytes=20,
        region=ClientRegion.CN,
        platform=ClientPlatform.PC,
    )

    assert first.event_key == "cn:pc_cn:100:101"
    assert second.event_key == "cn:pc_test_cn:100:101"
    assert first.event_key != second.event_key


def test_first_observation_message_declares_missing_baseline_without_fake_size() -> (
    None
):
    """首次观察没有 baseline 时必须明确暂无可比较大小，不能显示 0 B。"""

    text = messages.format_current(_snapshot("pc_cn", 101))
    assert "上次版本：暂无" in text
    assert "新增更新：暂无可比较大小" in text
    assert "0 B" not in text
