"""PR #27 复审回归契约：host 配置边界、资源并发和恢复入口。"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.config import DnabySettings, generate_astrbot_schema
from src.infrastructure.resources import (
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)
from src.infrastructure.resources import generation as generation_module
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.scheduler_state import SchedulerTaskState
from src.infrastructure.subscriptions import SubscriptionStore


class _CheckinProbe:
    async def auto_sign_all(self) -> str:
        return "auto-sign"

    async def clear_sign_records_before(self, _record_date: Any) -> int:
        return 0


async def _sleep_forever(_seconds: float) -> None:
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_astrbot_schema_normalization_preserves_legacy_scheduler_gate(
    tmp_path: Path,
) -> None:
    """真实 AstrBotConfig 归一化和重载必须保留旧 scheduled_enabled=false。"""

    config_path = tmp_path / "plugin-config.json"
    config_path.write_text(
        json.dumps({"sign_in": {"scheduled_enabled": False}}),
        encoding="utf-8",
    )

    from astrbot.core import AstrBotConfig

    schema = generate_astrbot_schema()
    host_config = AstrBotConfig(str(config_path), schema=schema)
    assert host_config["sign_in"]["scheduled_enabled"] is False

    settings = DnabySettings.from_config(host_config)
    assert settings.sign_in.scheduler_enabled_for_runtime is False

    restarted_config = AstrBotConfig(str(config_path), schema=schema)
    restarted_settings = DnabySettings.from_config(restarted_config)
    assert restarted_settings.sign_in.scheduler_enabled_for_runtime is False

    scheduler = SignScheduler(
        _CheckinProbe(),
        SubscriptionStore(tmp_path / "subscriptions.json"),
        sign_task_enabled=restarted_settings.sign_in.scheduler_enabled_for_runtime,
        sleep=_sleep_forever,
    )
    await scheduler.start()
    await asyncio.sleep(0)
    snapshot = await scheduler.registry.get_snapshot("dnaby_sign_daily")
    assert snapshot is not None
    assert snapshot.state is SchedulerTaskState.PAUSED
    assert [task.get_name() for task in scheduler._tasks] == ["dnaby_sign_cleanup"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_resource_sync_does_not_block_event_loop_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git/候选物化阻塞时，旧已验证 generation 仍可被 event loop 读取。"""

    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
    )
    coordinator.repository.mkdir(parents=True)
    old_root = coordinator.generations_root / ("a" * 40)
    new_root = coordinator.generations_root / ("b" * 40)
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    old_snapshot = ResourceSnapshot(
        commit_sha="a" * 40,
        root=old_root,
        manifest=SimpleNamespace(resource_version="v1"),
        player_resources=object(),
        encyclopedia_resources=object(),
        content_sha256="a" * 64,
    )
    new_snapshot = ResourceSnapshot(
        commit_sha="b" * 40,
        root=new_root,
        manifest=SimpleNamespace(resource_version="v2"),
        player_resources=object(),
        encyclopedia_resources=object(),
        content_sha256="b" * 64,
    )
    coordinator._current = old_snapshot

    entered = threading.Event()
    release = threading.Event()

    class _FakeSynchronizer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def validate(self) -> None:
            entered.set()
            release.wait()

        def fetch_main(self) -> None:
            return None

        def fetch_head_revision(self) -> str:
            return "b" * 40

        def archive_fetch_head(self, _archive: Path) -> None:
            return None

        def fast_forward_fetch_head(self) -> None:
            return None

    monkeypatch.setattr(generation_module, "ResourceSynchronizer", _FakeSynchronizer)

    def blocking_materialize(_synchronizer: Any, _commit_sha: str):
        return new_snapshot, False

    monkeypatch.setattr(coordinator, "_materialize", blocking_materialize)

    sync_task = asyncio.create_task(asyncio.to_thread(coordinator.synchronize))
    await asyncio.to_thread(entered.wait)

    probe_before_release: list[bool] = []

    async def read_resources() -> object:
        with coordinator.bind_renderer(
            SimpleNamespace(resources=None), "player_resources"
        ) as bound:
            return bound.resources

    async def event_loop_probe() -> None:
        await asyncio.sleep(0)
        probe_before_release.append(not release.is_set())

    handler_task = asyncio.create_task(read_resources())
    probe_task = asyncio.create_task(event_loop_probe())
    watchdog = threading.Timer(0.2, release.set)
    watchdog.start()
    try:
        await asyncio.gather(handler_task, probe_task)
    finally:
        release.set()
        watchdog.cancel()
    await sync_task

    assert handler_task.result() is old_snapshot.player_resources
    assert probe_before_release == [True]
