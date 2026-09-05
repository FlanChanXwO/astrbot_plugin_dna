"""Goal 6 CHECK-5：客户端 State v3 的 channel 一致性复查契约。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateBaseline,
    ClientUpdateChange,
    ClientUpdatePendingTarget,
    ClientUpdateStateError,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)

UTC_ISO = "2026-09-05T01:00:00+00:00"


def _snapshot(patch_version: int) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
        platform=ClientPlatform.PC,
        region=ClientRegion.CN,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=None,
        major=1,
        minor=5,
        revamp=192,
        patch_key=1,
    )


def _platform_only_change() -> ClientUpdateChange:
    return ClientUpdateChange(
        previous=_snapshot(100),
        current=_snapshot(101),
        added_size_bytes=10,
        region=ClientRegion.CN,
        platform=ClientPlatform.PC,
    )


def _v3_platform_pending_state() -> dict[str, object]:
    return {
        "schema_version": 3,
        "baselines": {},
        "pending_events": [
            {
                "event_key": "cn:pc:100:101",
                "change": {
                    "region": "cn",
                    "platform": "pc",
                    "previous": {
                        "region": "cn",
                        "platform": "pc",
                        "version_key": 100,
                        "patch_version": 100,
                        "resource_version_dir": None,
                        "version_text": "1.5.192.1",
                        "major": 1,
                        "minor": 5,
                        "revamp": 192,
                        "patch_key": 1,
                    },
                    "current": {
                        "region": "cn",
                        "platform": "pc",
                        "version_key": 101,
                        "patch_version": 101,
                        "resource_version_dir": None,
                        "version_text": "1.5.192.1",
                        "major": 1,
                        "minor": 5,
                        "revamp": 192,
                        "patch_key": 1,
                    },
                    "added_size_bytes": 10,
                },
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
async def test_v3_rejects_platform_only_pending_event_without_rewriting(
    tmp_path: Path,
) -> None:
    """v3 pending event 必须使用 canonical channel，失败不得改写原文件。"""

    path = tmp_path / "client_update_state.json"
    source = json.dumps(_v3_platform_pending_state(), separators=(",", ":")).encode()
    path.write_bytes(source)

    with pytest.raises(ClientUpdateStateError):
        await ClientUpdateStateStore(path).load()

    assert path.read_bytes() == source
    assert not path.with_name(f"{path.name}.v2.bak").exists()


@pytest.mark.asyncio
async def test_state_write_canonicalizes_platform_only_change_before_persisting(
    tmp_path: Path,
) -> None:
    """旧 platform transport seam 写入 v3 前必须转换为 canonical channel。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    previous = ClientUpdateBaseline(
        snapshot=_snapshot(100),
        observed_at=datetime.fromisoformat(UTC_ISO),
    )
    change = _platform_only_change()
    baseline = ClientUpdateBaseline(
        snapshot=change.current,
        observed_at=datetime.fromisoformat(UTC_ISO),
        last_change=change,
    )

    created = await store.save_baseline_with_pending_event(
        baseline,
        change,
        (ClientUpdatePendingTarget(origin="onebot:group:a"),),
    )

    assert created is not None
    assert created.event_key == "cn:pc_cn:100:101"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved["baselines"]) == {"cn:pc_cn"}
    assert saved["pending_events"][0]["event_key"] == "cn:pc_cn:100:101"
    assert saved["pending_events"][0]["change"]["channel_id"] == "pc_cn"
    assert saved["pending_events"][0]["change"]["previous"]["channel_id"] == "pc_cn"
    assert saved["pending_events"][0]["change"]["current"]["channel_id"] == "pc_cn"
    assert previous.snapshot.channel_id is None
