"""客户端更新 state v4 的 Source 基线与 pending 持久化测试。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.modules.client_updates import (
    STATE_VERSION,
    AppStoreVersionMetadata,
    ClientSourceVersion,
    ClientUpdateBaseline,
    ClientUpdateChange,
    ClientUpdatePendingTarget,
    ClientUpdateStateError,
    ClientUpdateStateStore,
    ManifestCdnVersionMetadata,
)


def _version(source_id: str, revision: str, *, order: int) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=f"1.6.{order}.1",
        revision_id=revision,
        order_key=(order, order),
        provider_metadata=ManifestCdnVersionMetadata(
            version_key=order,
            patch_version=order,
            resource_version_dir=None,
        ),
    )


@pytest.mark.asyncio
async def test_state_v4_round_trips_source_baseline_and_target_snapshot(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    previous = _version(source_id, "100", order=100)
    current = _version(source_id, "102", order=102)
    change = ClientUpdateChange(
        previous=previous,
        current=current,
        history_complete=True,
        added_size_bytes=2048,
        target_ids=("cn-official-pc",),
    )
    baseline = ClientUpdateBaseline(
        version=current,
        observed_at=datetime(2026, 9, 8, 10, 30, tzinfo=UTC),
        last_change=change,
    )
    target = ClientUpdatePendingTarget(
        origin="group:123",
        uid="user-1",
        bot_id="bot-1",
    )
    path = tmp_path / "client_updates.json"

    stored = await ClientUpdateStateStore(path).save_baseline_with_pending_event(
        baseline,
        change,
        (target,),
    )
    reloaded = ClientUpdateStateStore(path)

    assert STATE_VERSION == 4
    assert stored is not None
    assert await reloaded.get_baseline(source_id) == baseline
    assert await reloaded.pending_events() == (stored,)
    assert stored.event_key == f"{source_id}:100:102"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    assert tuple(payload["baselines"]) == (source_id,)
    assert payload["pending_events"][0]["change"]["target_ids"] == ["cn-official-pc"]
    assert "target_ids" not in payload["pending_events"][0]["targets"][0]


@pytest.mark.asyncio
async def test_state_v4_round_trips_app_store_provider_metadata(tmp_path) -> None:
    source_id = "cn-official-ios-app-store"
    version = ClientSourceVersion(
        source_id=source_id,
        version_text="1.6.0",
        revision_id="6470771372:1.6.0",
        order_key=None,
        provider_metadata=AppStoreVersionMetadata(
            track_id=6470771372,
            country="cn",
            release_date="2026-09-01T00:00:00Z",
        ),
    )
    baseline = ClientUpdateBaseline(
        version=version,
        observed_at=datetime(2026, 9, 8, 10, 45, tzinfo=UTC),
    )
    path = tmp_path / "client_updates.json"

    await ClientUpdateStateStore(path).save_baseline(baseline)

    assert await ClientUpdateStateStore(path).get_baseline(source_id) == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("schema_version", [1, 2, 3])
async def test_legacy_state_is_warned_and_ignored_without_backup(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    schema_version: int,
) -> None:
    path = tmp_path / "client_updates.json"
    original = json.dumps(
        {
            "schema_version": schema_version,
            "baselines": {"legacy:payload": {"must": "not be parsed"}},
            "pending_events": [{"must": "not be migrated"}],
        }
    )
    path.write_text(original, encoding="utf-8")
    store = ClientUpdateStateStore(path)

    with caplog.at_level(logging.WARNING):
        await store.load()

    assert await store.get_baseline("cn-official-pc-manifest") is None
    assert await store.pending_events() == ()
    assert path.read_text(encoding="utf-8") == original
    assert not tuple(tmp_path.glob("*.bak"))
    assert f"state v{schema_version}" in caplog.text


@pytest.mark.asyncio
async def test_first_write_after_ignored_legacy_state_creates_v4(tmp_path) -> None:
    path = tmp_path / "client_updates.json"
    path.write_text('{"schema_version": 3}', encoding="utf-8")
    store = ClientUpdateStateStore(path)
    version = _version("cn-official-pc-manifest", "100", order=100)

    await store.load()
    await store.save_baseline(
        ClientUpdateBaseline(
            version=version,
            observed_at=datetime(2026, 9, 8, 11, 0, tzinfo=UTC),
        )
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    assert tuple(payload["baselines"]) == ("cn-official-pc-manifest",)
    assert not tuple(tmp_path.glob("*.bak"))


@pytest.mark.asyncio
async def test_atomic_write_failure_restores_baseline_and_pending_memory(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = "cn-official-pc-manifest"
    path = tmp_path / "client_updates.json"
    store = ClientUpdateStateStore(path)
    initial = ClientUpdateBaseline(
        version=_version(source_id, "100", order=100),
        observed_at=datetime(2026, 9, 8, 11, 0, tzinfo=UTC),
    )
    await store.save_baseline(initial)
    original_bytes = path.read_bytes()
    current = _version(source_id, "102", order=102)
    change = ClientUpdateChange(
        previous=initial.version,
        current=current,
        history_complete=False,
        added_size_bytes=None,
        target_ids=("cn-official-pc",),
    )
    updated = ClientUpdateBaseline(
        version=current,
        observed_at=datetime(2026, 9, 8, 11, 5, tzinfo=UTC),
        last_change=change,
    )
    target = ClientUpdatePendingTarget(
        origin="group:123",
        uid="user-1",
    )

    def fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(ClientUpdateStateError, match="client update state is invalid"):
        await store.save_baseline_with_pending_event(updated, change, (target,))

    assert await store.get_baseline(source_id) == initial
    assert await store.pending_events() == ()
    assert path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_save_without_delivery_targets_advances_only_source_baseline(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    previous = _version(source_id, "100", order=100)
    current = _version(source_id, "102", order=102)
    change = ClientUpdateChange(
        previous=previous,
        current=current,
        history_complete=False,
        added_size_bytes=None,
        target_ids=("cn-official-pc",),
    )
    baseline = ClientUpdateBaseline(
        version=current,
        observed_at=datetime(2026, 9, 8, 11, 5, tzinfo=UTC),
        last_change=change,
    )
    store = ClientUpdateStateStore(tmp_path / "client_updates.json")

    stored = await store.save_baseline_with_pending_event(baseline, change, ())

    assert stored is None
    assert await store.get_baseline(source_id) == baseline
    assert await store.pending_events() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 4, "baselines": [], "pending_events": []},
        {"schema_version": 5, "baselines": {}, "pending_events": []},
        {"schema_version": 4, "baselines": {}, "pending_events": {}},
    ],
)
async def test_invalid_v4_or_unknown_state_is_reported_as_corrupt(
    tmp_path,
    payload: object,
) -> None:
    path = tmp_path / "client_updates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ClientUpdateStateError, match="client update state is invalid"):
        await ClientUpdateStateStore(path).load()
