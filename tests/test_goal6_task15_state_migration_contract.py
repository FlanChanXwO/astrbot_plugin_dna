"""Goal 6 T15：客户端更新 State v2→v3 迁移契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.client_updates import (
    STATE_VERSION,
    ClientRegion,
    ClientUpdateStateError,
    ClientUpdateStateStore,
)

UTC_ISO = "2026-09-05T01:00:00+00:00"


def _snapshot_payload(
    platform: str,
    patch_version: int,
    *,
    revamp: int = 192,
    resource_version_dir: str | None = None,
) -> dict[str, object]:
    return {
        "region": "cn",
        "platform": platform,
        "version_key": patch_version,
        "patch_version": patch_version,
        "resource_version_dir": resource_version_dir,
        "version_text": f"1.5.{revamp}.1",
        "major": 1,
        "minor": 5,
        "revamp": revamp,
        "patch_key": 1,
    }


def _v2_state_with_legacy_platform_keys() -> dict[str, object]:
    pc_previous = _snapshot_payload("pc", 100)
    pc_current = _snapshot_payload("pc", 101, revamp=193)
    pc_change = {
        "region": "cn",
        "platform": "pc",
        "previous": pc_previous,
        "current": pc_current,
        "added_size_bytes": 123,
    }
    return {
        "schema_version": 2,
        "baselines": {
            "cn:pc": {
                "snapshot": pc_current,
                "observed_at": UTC_ISO,
                "last_change": pc_change,
            },
            "cn:android": {
                "snapshot": _snapshot_payload(
                    "android",
                    200,
                    resource_version_dir="200",
                ),
                "observed_at": UTC_ISO,
                "last_change": None,
            },
        },
        "pending_events": [
            {
                "event_key": "cn:pc:100:101",
                "change": pc_change,
                "targets": [
                    {
                        "origin": "onebot:group:a",
                        "uid": "",
                        "bot_id": "onebot",
                        "status": "pending",
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_v2_state_migrates_platform_keys_and_pending_event_to_v3_channels(
    tmp_path: Path,
) -> None:
    """旧平台 key 与 pending event 必须迁移为固定 channel 身份并保留目标。"""

    path = tmp_path / "client_update_state.json"
    legacy_payload = _v2_state_with_legacy_platform_keys()
    legacy_bytes = json.dumps(
        legacy_payload,
        ensure_ascii=False,
        indent=4,
    ).encode("utf-8")
    path.write_bytes(legacy_bytes)

    store = ClientUpdateStateStore(path)
    await store.load()

    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert STATE_VERSION == 3
    assert migrated["schema_version"] == 3
    assert set(migrated["baselines"]) == {
        "cn:pc_cn",
        "cn:android_astc_cn",
    }
    assert "cn:pc" not in migrated["baselines"]
    assert "cn:android" not in migrated["baselines"]

    pc_baseline = await store.get_baseline(ClientRegion.CN, "pc_cn")
    assert pc_baseline is not None
    assert pc_baseline.snapshot.channel_id == "pc_cn"
    assert pc_baseline.last_change is not None
    assert pc_baseline.last_change.channel_id == "pc_cn"

    android_baseline = await store.get_baseline(
        ClientRegion.CN,
        "android_astc_cn",
    )
    assert android_baseline is not None
    assert android_baseline.snapshot.channel_id == "android_astc_cn"

    pending = await store.pending_events()
    assert len(pending) == 1
    assert pending[0].event_key == "cn:pc_cn:100:101"
    assert pending[0].change.channel_id == "pc_cn"
    assert [(target.origin, target.status) for target in pending[0].targets] == [
        ("onebot:group:a", "pending")
    ]

    backup_path = path.with_name(f"{path.name}.v2.bak")
    assert backup_path.read_bytes() == legacy_bytes


@pytest.mark.asyncio
async def test_state_v2_migration_is_idempotent_and_does_not_create_new_channel_baseline(
    tmp_path: Path,
) -> None:
    """重复加载不能改写迁移结果，也不能为未出现在旧状态中的渠道造基线。"""

    path = tmp_path / "client_update_state.json"
    legacy_payload = {
        "schema_version": 2,
        "baselines": {
            "cn:pc": {
                "snapshot": _snapshot_payload("pc", 100),
                "observed_at": UTC_ISO,
                "last_change": None,
            }
        },
        "pending_events": [],
    }
    legacy_bytes = json.dumps(legacy_payload, separators=(",", ":")).encode("utf-8")
    path.write_bytes(legacy_bytes)

    first = ClientUpdateStateStore(path)
    assert await first.get_baseline(ClientRegion.CN, "pc_cn") is not None
    migrated_bytes = path.read_bytes()
    backup_bytes = path.with_name(f"{path.name}.v2.bak").read_bytes()

    second = ClientUpdateStateStore(path)
    await second.load()
    assert path.read_bytes() == migrated_bytes
    assert path.with_name(f"{path.name}.v2.bak").read_bytes() == backup_bytes
    assert await second.get_baseline(ClientRegion.CN, "android_astc_cn") is None


@pytest.mark.asyncio
async def test_v3_state_writes_canonical_channel_key_and_schema_version(
    tmp_path: Path,
) -> None:
    """新写入状态必须使用 v3 和 channel key，而不是回写 platform key。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    await store.save_baseline(
        # 通过原始 JSON 迁移契约验证 channel key；具体 DTO 构造由已有测试覆盖。
        await _baseline_for_test("pc_cn"),
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert set(saved["baselines"]) == {"cn:pc_cn"}


async def _baseline_for_test(channel_id: str):
    from datetime import datetime

    from src.modules.client_updates import ClientUpdateBaseline, ClientVersionSnapshot

    return ClientUpdateBaseline(
        snapshot=ClientVersionSnapshot(
            channel_id=channel_id,
            platform="pc",
            region="cn",
            version_key=100,
            patch_version=100,
            resource_version_dir=None,
            major=1,
            minor=5,
            revamp=192,
            patch_key=1,
        ),
        observed_at=datetime.fromisoformat(UTC_ISO),
    )


@pytest.mark.asyncio
async def test_v3_legacy_platform_key_fails_without_rewriting_state(
    tmp_path: Path,
) -> None:
    """v3 不接受旧 platform key，失败时保留原文且不创建迁移备份。"""

    path = tmp_path / "client_update_state.json"
    invalid = {
        "schema_version": 3,
        "baselines": {
            "cn:pc": {
                "snapshot": _snapshot_payload("pc", 100),
                "observed_at": UTC_ISO,
                "last_change": None,
            }
        },
        "pending_events": [],
    }
    invalid_bytes = json.dumps(invalid).encode("utf-8")
    path.write_bytes(invalid_bytes)

    with pytest.raises(ClientUpdateStateError):
        await ClientUpdateStateStore(path).load()

    assert path.read_bytes() == invalid_bytes
    assert not path.with_name(f"{path.name}.v2.bak").exists()
