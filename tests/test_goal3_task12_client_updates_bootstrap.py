"""Goal 3 / Task 12：客户端更新轮询 service 与 bootstrap Red 契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.infrastructure.persistence import AsyncDatabase
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateObservation,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)

CLIENT_UPDATE_TASK_ID = "dnaby_client_update_poll"


def _snapshot(platform: ClientPlatform, patch_version: int) -> ClientVersionSnapshot:
    """构造轮询测试所需的最小有效版本快照。"""

    return ClientVersionSnapshot(
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


class _SequenceTransport:
    """按平台提供两轮观察结果，并记录 scheduler 传入的历史基线。"""

    def __init__(self) -> None:
        self.calls: list[tuple[ClientPlatform, int | None]] = []
        self._observations = {
            ClientPlatform.PC: [
                ClientUpdateObservation(_snapshot(ClientPlatform.PC, 100)),
                ClientUpdateObservation(
                    _snapshot(ClientPlatform.PC, 101),
                    patch_sizes={101: 10},
                ),
            ],
            ClientPlatform.ANDROID: [
                ClientUpdateObservation(_snapshot(ClientPlatform.ANDROID, 200)),
                ClientUpdateObservation(
                    _snapshot(ClientPlatform.ANDROID, 201),
                    patch_sizes={201: 20},
                ),
            ],
        }

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        normalized = ClientPlatform(platform)
        self.calls.append((normalized, previous_patch_version))
        return self._observations[normalized].pop(0)


class _UnusedTransport:
    """bootstrap 构造测试中不应被提前调用的 transport。"""

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        raise AssertionError(f"unexpected transport call: {platform}")


@pytest.mark.asyncio
async def test_client_update_service_poll_now_observes_both_platforms(
    tmp_path: Path,
) -> None:
    """轮询 service 应按固定平台顺序建立并推进独立基线。"""

    transport = _SequenceTransport()
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(state, transport=transport)

    assert await service.poll_now() == 0
    assert await service.poll_now() == 2
    assert transport.calls == [
        (ClientPlatform.PC, None),
        (ClientPlatform.ANDROID, None),
        (ClientPlatform.PC, 100),
        (ClientPlatform.ANDROID, 200),
    ]

    pc_baseline = await state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    android_baseline = await state.get_baseline(
        ClientRegion.CN,
        ClientPlatform.ANDROID,
    )
    assert pc_baseline is not None
    assert pc_baseline.snapshot.patch_version == 101
    assert pc_baseline.last_change is not None
    assert pc_baseline.last_change.added_size_bytes == 10
    assert android_baseline is not None
    assert android_baseline.snapshot.patch_version == 201
    assert android_baseline.last_change is not None
    assert android_baseline.last_change.added_size_bytes == 20


@pytest.mark.asyncio
async def test_bootstrap_wires_client_update_state_service_scheduler_and_lifecycle(
    tmp_path: Path,
) -> None:
    """bootstrap 应把客户端更新组件接到共享 registry 和生命周期。"""

    from src.bootstrap import build_runtime
    from src.infrastructure.client_updates_scheduler import ClientUpdatesScheduler
    from src.infrastructure.scheduler_state import SchedulerRegistry
    from src.modules.admin.api import AdminApiService

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    transport = _UnusedTransport()
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {
            "notifications": {
                "client_update_enabled": False,
                "client_update_check_minutes": 15,
            }
        },
        database=database,
        client_updates_transport=transport,
    )

    registry = cast(SchedulerRegistry, runtime.services["scheduler_registry"])
    state = runtime.services["client_update_state"]
    service = runtime.services["client_update_service"]
    scheduler = runtime.services["client_updates_scheduler"]
    admin_api_service = cast(
        AdminApiService,
        runtime.services["admin_api_service"],
    )

    assert isinstance(registry, SchedulerRegistry)
    assert isinstance(state, ClientUpdateStateStore)
    assert state.path == (tmp_path / "client_update_state.json").resolve()
    assert isinstance(service, ClientUpdateService)
    assert service.transport is transport
    assert isinstance(scheduler, ClientUpdatesScheduler)
    assert scheduler.client_updates is service
    assert scheduler.registry is registry
    assert admin_api_service.schedulers[CLIENT_UPDATE_TASK_ID] is scheduler

    task_snapshot = await registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
    assert task_snapshot is not None
    assert task_snapshot.schedule == "interval@15m"
    assert task_snapshot.targets == ("client_update_subscriptions",)
    assert await registry.is_enabled(CLIENT_UPDATE_TASK_ID) is False
    # lifecycle 保存的是构造完成时的 bound method，而不是公告 scheduler 的 hook。
    assert any(
        getattr(hook, "__self__", None) is scheduler
        for hook in runtime.lifecycle._start_hooks
    )
    assert any(
        getattr(hook, "__self__", None) is scheduler
        for hook in runtime.lifecycle._stop_hooks
    )


@pytest.mark.asyncio
async def test_bootstrap_client_update_task_uses_independent_configured_schedule(
    tmp_path: Path,
) -> None:
    """客户端更新周期应独立于公告周期写入 registry。"""

    from src.bootstrap import build_runtime
    from src.infrastructure.scheduler_state import SchedulerRegistry

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {
            "notifications": {
                "announcement_check_minutes": 5,
                "client_update_check_minutes": 17,
            }
        },
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
        client_updates_transport=_UnusedTransport(),
    )

    registry = cast(SchedulerRegistry, runtime.services["scheduler_registry"])
    client_snapshot = await registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
    announcement_snapshot = await registry.get_snapshot("dnaby_ann_poll")
    assert client_snapshot is not None
    assert announcement_snapshot is not None
    assert client_snapshot.schedule == "interval@17m"
    assert announcement_snapshot.schedule == "interval@5m"
