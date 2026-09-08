"""Goal 6 T27：scheduler、真实 service 与 State v3 的启动组合证据。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.infrastructure.client_updates_scheduler import ClientUpdatesScheduler
from src.infrastructure.scheduler_state import SchedulerRegistry
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateObservation,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)


class _ManualClock:
    def __init__(self) -> None:
        self.current = datetime(
            2026,
            9,
            6,
            12,
            0,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )

    def __call__(self) -> datetime:
        return self.current

    def advance(self, minutes: int) -> None:
        self.current += timedelta(minutes=minutes)


class _CycleSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []
        self.first_entered = asyncio.Event()
        self.first_release = asyncio.Event()
        self.second_entered = asyncio.Event()
        self.second_release = asyncio.Event()
        self.tail_release = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) == 1:
            self.first_entered.set()
            await self.first_release.wait()
            return
        if len(self.calls) == 2:
            self.second_entered.set()
            await self.second_release.wait()
            return
        await self.tail_release.wait()


class _ChannelTransport:
    def __init__(
        self,
        responses: Mapping[
            str,
            Sequence[ClientUpdateObservation],
        ],
    ) -> None:
        self.responses = {channel: list(items) for channel, items in responses.items()}
        self.calls: list[tuple[str, int | None]] = []

    async def get_observation(
        self,
        channel_id: str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        self.calls.append((channel_id, previous_patch_version))
        return self.responses[channel_id].pop(0)


class _RecordingDelivery:
    def __init__(self) -> None:
        self.rounds: list[tuple] = []

    async def deliver(self, changes: Sequence[object]) -> int:
        self.rounds.append(tuple(changes))
        return len(changes)


def _observation(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
    *,
    patch_sizes: Mapping[int, int] | None = None,
) -> ClientUpdateObservation:
    snapshot = ClientVersionSnapshot(
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
        revamp=patch_version,
        patch_key=1,
    )
    return ClientUpdateObservation(
        snapshot=snapshot,
        patch_sizes=patch_sizes or {},
    )


@pytest.mark.asyncio
async def test_scheduler_start_persists_channel_baselines_before_first_wait(
    tmp_path: Path,
) -> None:
    """真实 scheduler 首轮启动要先写入独立 channel baseline，再进入周期等待。"""

    transport = _ChannelTransport(
        {
            "pc_cn": [
                _observation("pc_cn", ClientPlatform.PC, 100),
                _observation("pc_cn", ClientPlatform.PC, 101, patch_sizes={101: 11}),
            ],
            "android_astc_cn": [
                _observation("android_astc_cn", ClientPlatform.ANDROID, 200),
                _observation(
                    "android_astc_cn",
                    ClientPlatform.ANDROID,
                    201,
                    patch_sizes={201: 22},
                ),
            ],
        }
    )
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(
        state,
        transport=transport,
        channels=("pc_cn", "android_astc_cn"),
    )
    delivery = _RecordingDelivery()
    clock = _ManualClock()
    sleep = _CycleSleep()
    scheduler = ClientUpdatesScheduler(
        service,
        delivery,
        check_minutes=1,
        now=clock,
        sleep=sleep,
        registry=SchedulerRegistry(),
    )

    try:
        await scheduler.start()
        await sleep.first_entered.wait()

        first_state = ClientUpdateStateStore(state.path)
        pc_baseline = await first_state.get_baseline(ClientRegion.CN, "pc_cn")
        android_baseline = await first_state.get_baseline(
            ClientRegion.CN,
            "android_astc_cn",
        )
        assert pc_baseline is not None
        assert android_baseline is not None
        assert pc_baseline.snapshot.channel_id == "pc_cn"
        assert android_baseline.snapshot.channel_id == "android_astc_cn"
        assert pc_baseline.snapshot.patch_version == 100
        assert android_baseline.snapshot.patch_version == 200
        assert pc_baseline.last_change is None
        assert android_baseline.last_change is None
        assert await first_state.pending_events() == ()

        persisted = json.loads(state.path.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == 3
        assert set(persisted["baselines"]) == {
            "cn:pc_cn",
            "cn:android_astc_cn",
        }
        assert all(
            baseline["last_change"] is None
            for baseline in persisted["baselines"].values()
        )
        assert delivery.rounds == [()]

        clock.advance(1)
        sleep.first_release.set()
        await sleep.second_entered.wait()

        assert sleep.calls == [60, 60]
        assert [
            (
                change.channel_id,
                change.previous.patch_version,
                change.current.patch_version,
            )
            for change in delivery.rounds[1]
        ] == [
            ("pc_cn", 100, 101),
            ("android_astc_cn", 200, 201),
        ]
        assert transport.calls == [
            ("pc_cn", None),
            ("android_astc_cn", None),
            ("pc_cn", 100),
            ("android_astc_cn", 200),
        ]

        second_state = ClientUpdateStateStore(state.path)
        pc_updated = await second_state.get_baseline(ClientRegion.CN, "pc_cn")
        android_updated = await second_state.get_baseline(
            ClientRegion.CN,
            "android_astc_cn",
        )
        assert pc_updated is not None
        assert android_updated is not None
        assert pc_updated.snapshot.channel_id == "pc_cn"
        assert android_updated.snapshot.channel_id == "android_astc_cn"
        assert pc_updated.snapshot.patch_version == 101
        assert android_updated.snapshot.patch_version == 201
        assert pc_updated.last_change is not None
        assert android_updated.last_change is not None
        assert pc_updated.last_change.channel_id == "pc_cn"
        assert android_updated.last_change.channel_id == "android_astc_cn"
        assert pc_updated.last_change.previous.patch_version == 100
        assert android_updated.last_change.previous.patch_version == 200
    finally:
        sleep.first_release.set()
        sleep.second_release.set()
        sleep.tail_release.set()
        await scheduler.stop()
