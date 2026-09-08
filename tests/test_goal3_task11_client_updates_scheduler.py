"""Goal 3 / Task 11：客户端更新 scheduler 与配置的 Red 契约。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.infrastructure.config import (
    DnabySettings,
    NotificationSettings,
    generate_astrbot_schema,
)
from src.infrastructure.scheduler_state import SchedulerRegistry, SchedulerTaskState
from src.modules.client_updates import ClientUpdateChange

CLIENT_UPDATE_TASK_ID = "dnaby_client_update_poll"


class _NoopDelivery:
    """旧 scheduler 行为测试使用的无操作投递端。"""

    async def deliver(self, _changes: tuple[ClientUpdateChange, ...]) -> int:
        return 0


class _FakeClientUpdates:
    """为 scheduler 契约提供可观察的轮询服务。"""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0
        self.called = asyncio.Event()

    async def poll_now(self) -> tuple[ClientUpdateChange, ...]:
        self.calls += 1
        self.called.set()
        if self.error is not None:
            raise self.error
        return ()


class _BlockingSleep:
    """让测试不依赖真实时钟，并能在 start 后确认 loop 已经挂起。"""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.entered.set()
        await self.release.wait()


class _ImmediateThenBlockingSleep(_BlockingSleep):
    """第一次 sleep 立即返回，驱动一轮 poll；后续 sleep 保持任务可取消。"""

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) == 1:
            return
        self.entered.set()
        await self.release.wait()


def _build_scheduler(
    tmp_path: Path,
    client_updates: _FakeClientUpdates,
    sleep: _BlockingSleep,
    *,
    enabled: bool = True,
    check_minutes: int = 60,
):
    """按预期的基础设施边界构造独立客户端更新 scheduler。"""

    from src.infrastructure.client_updates_scheduler import ClientUpdatesScheduler

    registry = SchedulerRegistry(tmp_path / "scheduler_state.json")
    scheduler = ClientUpdatesScheduler(
        client_updates,
        _NoopDelivery(),
        enabled=enabled,
        check_minutes=check_minutes,
        registry=registry,
        sleep=sleep,
    )
    return scheduler, registry


def test_client_update_settings_have_independent_defaults_and_positive_interval() -> (
    None
):
    """客户端更新配置默认开启、约每小时检查，且周期必须为正整数。"""

    defaults = NotificationSettings()
    assert defaults.client_update_enabled is True
    assert defaults.client_update_check_minutes == 60
    assert defaults.client_update_merge_forward is True

    loaded = DnabySettings.from_config(
        {
            "notifications": {
                "client_update_enabled": False,
                "client_update_check_minutes": 15,
                "client_update_merge_forward": False,
            }
        }
    )
    assert loaded.notifications.client_update_enabled is False
    assert loaded.notifications.client_update_check_minutes == 15
    assert loaded.notifications.client_update_merge_forward is False

    with pytest.raises(ValidationError):
        NotificationSettings(client_update_check_minutes=0)


def test_generated_schema_declares_client_update_configuration() -> None:
    """typed schema 必须在独立分组生成客户端更新配置及其产品默认值。"""

    items = generate_astrbot_schema()["client_updates"]["items"]

    assert items["enabled"]["type"] == "bool"
    assert items["enabled"]["default"] is True
    assert items["check_minutes"]["type"] == "int"
    assert items["check_minutes"]["default"] == 60
    assert items["channels"]["type"] == "list"
    assert set(items["channels"]["options"]) >= {"pc_cn", "android_astc_cn"}
    assert items["merge_forward"]["type"] == "bool"
    assert items["merge_forward"]["default"] is True


@pytest.mark.asyncio
async def test_client_updates_scheduler_registers_independent_default_hourly_task(
    tmp_path: Path,
) -> None:
    """scheduler 只注册独立任务，并使用 interval@60m 的默认周期。"""

    sleep = _BlockingSleep()
    scheduler, registry = _build_scheduler(
        tmp_path,
        _FakeClientUpdates(),
        sleep,
    )

    snapshot = await registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
    assert snapshot is not None
    assert snapshot.name == "客户端更新轮询"
    assert snapshot.schedule == "interval@60m"
    assert snapshot.targets == ("client_update_subscriptions",)
    assert await registry.is_enabled(CLIENT_UPDATE_TASK_ID) is True

    await scheduler.start()
    await sleep.entered.wait()
    assert {task.get_name() for task in scheduler._tasks} == {CLIENT_UPDATE_TASK_ID}
    await scheduler.stop()


@pytest.mark.asyncio
async def test_client_updates_scheduler_honors_disabled_switch(tmp_path: Path) -> None:
    """关闭独立开关时不创建客户端更新后台任务。"""

    sleep = _BlockingSleep()
    client_updates = _FakeClientUpdates()
    scheduler, registry = _build_scheduler(
        tmp_path,
        client_updates,
        sleep,
        enabled=False,
    )

    assert await registry.is_enabled(CLIENT_UPDATE_TASK_ID) is False
    await scheduler.start()
    assert scheduler.started is True
    assert scheduler._tasks == []
    assert client_updates.calls == 0
    await scheduler.stop()


@pytest.mark.asyncio
async def test_client_updates_scheduler_start_stop_are_idempotent(
    tmp_path: Path,
) -> None:
    """重复 start/stop 不得创建重复任务或在第二次 stop 抛错。"""

    sleep = _BlockingSleep()
    scheduler, _registry = _build_scheduler(
        tmp_path,
        _FakeClientUpdates(),
        sleep,
    )

    await scheduler.start()
    await scheduler.start()
    await sleep.entered.wait()
    assert scheduler.started is True
    assert len(scheduler._tasks) == 1

    await scheduler.stop()
    await scheduler.stop()
    assert scheduler.started is False
    assert scheduler._tasks == []


@pytest.mark.asyncio
async def test_client_updates_scheduler_marks_poll_failure_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轮询异常进入 registry error 状态，且状态不泄露上游异常原文。"""

    sleep = _ImmediateThenBlockingSleep()
    client_updates = _FakeClientUpdates(RuntimeError("upstream secret detail"))
    scheduler, registry = _build_scheduler(
        tmp_path,
        client_updates,
        sleep,
    )

    error_marked = asyncio.Event()
    original_mark_error = registry.mark_error

    async def mark_error(task_id: str) -> None:
        await original_mark_error(task_id)
        error_marked.set()

    monkeypatch.setattr(registry, "mark_error", mark_error)

    await scheduler.start()
    await client_updates.called.wait()
    await error_marked.wait()

    snapshot = await registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
    assert snapshot is not None
    assert snapshot.state is SchedulerTaskState.ERROR
    assert snapshot.last_error == "task execution failed"
    assert "upstream secret detail" not in (snapshot.last_error or "")

    await scheduler.stop()
