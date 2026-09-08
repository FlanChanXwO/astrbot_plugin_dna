"""Goal 3 / Task 04：观察基线、变化检测与状态原子性 Red 契约。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.modules.client_updates.contracts import (
    ClientPlatform,
    ClientRegion,
    ClientVersionSnapshot,
)
from src.modules.client_updates.service import (
    ClientUpdateRollbackError,
    ClientUpdateService,
)
from src.modules.client_updates.state import (
    ClientUpdateBaseline,
    ClientUpdateStateError,
    ClientUpdateStateStore,
)

UTC = timezone.utc
FIRST_OBSERVED_AT = datetime(2026, 9, 2, 1, 0, tzinfo=UTC)
SECOND_OBSERVED_AT = datetime(2026, 9, 2, 2, 0, tzinfo=UTC)


def _snapshot(
    patch_version: int,
    *,
    platform: ClientPlatform = ClientPlatform.PC,
    version_key: int | None = None,
) -> ClientVersionSnapshot:
    """构造与测试无关的最小平台快照。"""

    key = patch_version if version_key is None else version_key
    resource_dir = str(key) if platform is ClientPlatform.ANDROID else None
    return ClientVersionSnapshot(
        platform=platform,
        region=ClientRegion.CN,
        version_key=key,
        patch_version=patch_version,
        resource_version_dir=resource_dir,
        major=1,
        minor=5,
        revamp=192,
        patch_key=patch_version,
    )


def _canonical_snapshot(snapshot: ClientVersionSnapshot) -> ClientVersionSnapshot:
    """状态边界会把旧 platform-only 快照落为固定 channel。"""

    channel_id = (
        "pc_cn" if snapshot.platform is ClientPlatform.PC else "android_astc_cn"
    )
    return replace(snapshot, channel_id=channel_id)


def _baseline(
    snapshot: ClientVersionSnapshot,
    *,
    observed_at: datetime = FIRST_OBSERVED_AT,
) -> ClientUpdateBaseline:
    return ClientUpdateBaseline(snapshot=snapshot, observed_at=observed_at)


async def _observe(
    service: ClientUpdateService,
    snapshot: ClientVersionSnapshot,
    *,
    observed_at: datetime = FIRST_OBSERVED_AT,
    patch_sizes: Mapping[int, int] | None = None,
):
    return await service.observe(
        snapshot,
        observed_at=observed_at,
        patch_sizes={} if patch_sizes is None else patch_sizes,
    )


@pytest.mark.asyncio
async def test_first_observation_builds_baseline_without_change(tmp_path: Path) -> None:
    """第一次成功观察只建立基线，不生成可推送变化。"""

    store = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(store)
    current = _snapshot(100)

    change = await _observe(service, current)

    assert change is None
    saved = await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert saved is not None
    assert saved.snapshot == _canonical_snapshot(current)
    assert saved.observed_at == FIRST_OBSERVED_AT
    assert saved.last_change is None


@pytest.mark.asyncio
async def test_unchanged_version_does_not_generate_a_second_change(
    tmp_path: Path,
) -> None:
    """版本未变化时不重复生成更新事件，但要保留最近成功观察时间。"""

    store = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(store)
    current = _snapshot(100)
    await _observe(service, current, observed_at=FIRST_OBSERVED_AT)

    change = await _observe(
        service,
        current,
        observed_at=SECOND_OBSERVED_AT,
        patch_sizes={100: 4096},
    )

    assert change is None
    saved = await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert saved is not None
    assert saved.snapshot == _canonical_snapshot(current)
    assert saved.observed_at == SECOND_OBSERVED_AT
    assert saved.last_change is None


@pytest.mark.asyncio
async def test_multiple_new_patches_are_summed_between_successful_observations(
    tmp_path: Path,
) -> None:
    """跨多个成功观察到的补丁只汇总开区间外的新增补丁。"""

    store = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(store)
    previous = _snapshot(100)
    current = _snapshot(103)
    await _observe(service, previous, observed_at=FIRST_OBSERVED_AT)

    change = await _observe(
        service,
        current,
        observed_at=SECOND_OBSERVED_AT,
        patch_sizes={
            99: 1,
            100: 2,
            101: 1024,
            102: 2048,
            103: 4096,
            104: 8192,
        },
    )

    assert change is not None
    assert change.previous == _canonical_snapshot(previous)
    assert change.current == _canonical_snapshot(current)
    assert change.added_size_bytes == 1024 + 2048 + 4096
    saved = await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert saved is not None
    assert saved.snapshot == _canonical_snapshot(current)
    assert saved.last_change == change


@pytest.mark.asyncio
async def test_version_rollback_preserves_the_last_successful_baseline(
    tmp_path: Path,
) -> None:
    """服务端版本回退显式失败，不能覆盖最近一次成功基线。"""

    store = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(store)
    previous = _snapshot(100)
    await _observe(service, previous)

    with pytest.raises(ClientUpdateRollbackError):
        await _observe(
            service,
            _snapshot(99),
            observed_at=SECOND_OBSERVED_AT,
            patch_sizes={99: 512},
        )

    saved = await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert saved is not None
    assert saved.snapshot == _canonical_snapshot(previous)
    assert saved.observed_at == FIRST_OBSERVED_AT
    assert saved.last_change is None


@pytest.mark.asyncio
async def test_repeating_the_same_new_version_does_not_duplicate_change(
    tmp_path: Path,
) -> None:
    """同一新版本重复观察不再产生第二条变化，最近变化摘要保持稳定。"""

    store = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(store)
    previous = _snapshot(100)
    current = _snapshot(103)
    await _observe(service, previous, observed_at=FIRST_OBSERVED_AT)
    first_change = await _observe(
        service,
        current,
        observed_at=SECOND_OBSERVED_AT,
        patch_sizes={101: 1024, 102: 2048, 103: 4096},
    )
    assert first_change is not None

    repeated = await _observe(
        service,
        current,
        observed_at=datetime(2026, 9, 2, 3, 0, tzinfo=UTC),
        patch_sizes={101: 9999, 102: 9999, 103: 9999},
    )

    assert repeated is None
    saved = await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert saved is not None
    assert saved.snapshot == _canonical_snapshot(current)
    assert saved.last_change == first_change


@pytest.mark.asyncio
async def test_state_store_round_trips_typed_baseline_and_schema_version(
    tmp_path: Path,
) -> None:
    """状态文件保存显式 schema 版本，并能恢复安卓资源目录等 typed 字段。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    baseline = _baseline(_snapshot(100, platform=ClientPlatform.ANDROID))

    await store.save_baseline(baseline)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw["schema_version"] == 3

    reloaded = ClientUpdateStateStore(path)
    restored = await reloaded.get_baseline(ClientRegion.CN, ClientPlatform.ANDROID)
    assert restored.snapshot == _canonical_snapshot(baseline.snapshot)
    assert restored.observed_at == baseline.observed_at
    assert restored is not None
    assert restored.snapshot.resource_version_dir == "100"


@pytest.mark.asyncio
async def test_corrupt_state_fails_explicitly_without_resetting_file(
    tmp_path: Path,
) -> None:
    """JSON 损坏时显式报错，不能静默回到空状态。"""

    path = tmp_path / "client_update_state.json"
    corrupt = "{ not valid json"
    path.write_text(corrupt, encoding="utf-8")
    store = ClientUpdateStateStore(path)

    with pytest.raises(ClientUpdateStateError):
        await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)

    assert path.read_text(encoding="utf-8") == corrupt


@pytest.mark.asyncio
async def test_invalid_state_schema_fails_explicitly_without_resetting_file(
    tmp_path: Path,
) -> None:
    """版本或字段结构非法时显式失败，不接受默认空映射。"""

    path = tmp_path / "client_update_state.json"
    invalid = {"schema_version": 999, "baselines": {}}
    path.write_text(json.dumps(invalid), encoding="utf-8")
    store = ClientUpdateStateStore(path)

    with pytest.raises(ClientUpdateStateError):
        await store.get_baseline(ClientRegion.CN, ClientPlatform.PC)

    assert json.loads(path.read_text(encoding="utf-8")) == invalid


@pytest.mark.asyncio
async def test_atomic_state_replace_failure_keeps_previous_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """原子替换失败时保留旧状态文件，不能留下半写入的最终文件。"""

    path = tmp_path / "client_update_state.json"
    store = ClientUpdateStateStore(path)
    original = _baseline(_snapshot(100))
    replacement = _baseline(_snapshot(103), observed_at=SECOND_OBSERVED_AT)
    await store.save_baseline(original)
    previous_bytes = path.read_bytes()
    original_replace = Path.replace

    def fail_final_replace(self: Path, target: str | Path) -> Path:
        if Path(target) == path:
            raise OSError("simulated state replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_final_replace)

    with pytest.raises(ClientUpdateStateError):
        await store.save_baseline(replacement)

    assert path.read_bytes() == previous_bytes
    reloaded = ClientUpdateStateStore(path)
    restored = await reloaded.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    assert restored == replace(
        original, snapshot=_canonical_snapshot(original.snapshot)
    )
