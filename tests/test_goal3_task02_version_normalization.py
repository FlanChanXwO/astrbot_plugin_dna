"""Goal 3 / Task 02：版本模型与补丁大小归一化的 Red 测试。"""

from __future__ import annotations

from typing import Any

import pytest

from src.modules.client_updates.contracts import (
    ClientPlatform,
    ClientUpdateStructureError,
    parse_version_list,
    sum_patch_file_sizes,
)


def _version_entry(
    patch_version: int,
    *,
    major: int = 1,
    minor: int = 5,
    revamp: int = 192,
    patch_key: int = 1,
) -> dict[str, Any]:
    return {
        "major": major,
        "minor": minor,
        "revamp": revamp,
        "patchKey": patch_key,
        "patchVersion": patch_version,
    }


def _manifest(platform_key: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pakFilesMap": {
            platform_key: {
                "pakFileInfos": entries,
            }
        }
    }


def test_parse_pc_version_formats_display_and_keeps_patch_version() -> None:
    payload = {
        "versionList": {
            "1410192": _version_entry(1410192, revamp=192),
        }
    }

    version = parse_version_list(payload, platform=ClientPlatform.PC)

    assert version.platform is ClientPlatform.PC
    assert version.version_key == 1410192
    assert version.patch_version == 1410192
    assert version.version_text == "1.5.192.1"


def test_parse_android_version_keeps_the_numeric_resource_directory_key() -> None:
    payload = {
        "versionList": {
            "1010162": _version_entry(1410162, revamp=162),
            "1010184": _version_entry(1410184, revamp=184),
        }
    }

    version = parse_version_list(payload, platform=ClientPlatform.ANDROID)

    assert version.platform is ClientPlatform.ANDROID
    assert version.version_key == 1010184
    assert version.patch_version == 1410184
    assert version.resource_version_dir == "1010184"
    assert version.version_text == "1.5.184.1"


def test_version_list_keys_are_sorted_numerically_not_lexicographically() -> None:
    payload = {
        "versionList": {
            "9": _version_entry(9, revamp=9),
            "10": _version_entry(10, revamp=10),
        }
    }

    version = parse_version_list(payload, platform=ClientPlatform.PC)

    assert version.version_key == 10
    assert version.patch_version == 10
    assert version.version_text == "1.5.10.1"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"versionList": []},
        {"versionList": {}},
        {"versionList": {"1410192": {"major": 1}}},
        {"versionList": {"not-a-number": _version_entry(1410192)}},
    ],
)
def test_parse_version_list_rejects_malformed_structures(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ClientUpdateStructureError):
        parse_version_list(payload, platform=ClientPlatform.PC)


@pytest.mark.parametrize(
    ("platform", "platform_key"),
    [
        (ClientPlatform.PC, "WindowsNoEditor"),
        (ClientPlatform.ANDROID, "Android_ASTC"),
    ],
)
def test_sum_patch_file_sizes_combines_both_manifests_and_deduplicates(
    platform: ClientPlatform,
    platform_key: str,
) -> None:
    pak_files_info = _manifest(
        platform_key,
        [
            {"fileName": "shared.pak", "fileSize": 100},
            {"fileName": "pak-only.pak", "fileSize": 50},
            {"fileName": "shared.pak", "fileSize": 100},
        ],
    )
    res_discrete_info = _manifest(
        platform_key,
        [
            {"fileName": "shared.pak", "fileSize": 100},
            {"fileName": "res-only.pak", "fileSize": 25},
        ],
    )

    total_size = sum_patch_file_sizes(
        platform=platform,
        pak_files_info=pak_files_info,
        res_discrete_info=res_discrete_info,
    )

    assert total_size == 175


def test_sum_patch_file_sizes_allows_empty_resource_lists() -> None:
    empty_manifest = _manifest("WindowsNoEditor", [])

    assert (
        sum_patch_file_sizes(
            platform=ClientPlatform.PC,
            pak_files_info=empty_manifest,
            res_discrete_info=empty_manifest,
        )
        == 0
    )


def test_sum_patch_file_sizes_rejects_conflicting_duplicate_file_sizes() -> None:
    pak_files_info = _manifest(
        "WindowsNoEditor",
        [{"fileName": "same.pak", "fileSize": 100}],
    )
    res_discrete_info = _manifest(
        "WindowsNoEditor",
        [{"fileName": "same.pak", "fileSize": 101}],
    )

    with pytest.raises(ClientUpdateStructureError):
        sum_patch_file_sizes(
            platform=ClientPlatform.PC,
            pak_files_info=pak_files_info,
            res_discrete_info=res_discrete_info,
        )


@pytest.mark.parametrize(
    "bad_manifest",
    [
        [],
        {},
        {"pakFilesMap": {}},
        {"pakFilesMap": {"WindowsNoEditor": {}}},
        {
            "pakFilesMap": {
                "WindowsNoEditor": {
                    "pakFileInfos": [{}],
                }
            }
        },
        {
            "pakFilesMap": {
                "WindowsNoEditor": {
                    "pakFileInfos": [{"fileName": "bad.pak", "fileSize": -1}],
                }
            }
        },
        {
            "pakFilesMap": {
                "WindowsNoEditor": {
                    "pakFileInfos": [{"fileName": "bad.pak", "fileSize": True}],
                }
            }
        },
    ],
)
def test_sum_patch_file_sizes_rejects_manifest_structure_errors(
    bad_manifest: Any,
) -> None:
    valid_manifest = _manifest("WindowsNoEditor", [])

    with pytest.raises(ClientUpdateStructureError):
        sum_patch_file_sizes(
            platform=ClientPlatform.PC,
            pak_files_info=bad_manifest,
            res_discrete_info=valid_manifest,
        )
