"""Goal 2 Task 08：统一调度 registry、可观测状态与永久 tombstone。"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.infrastructure.notices_scheduler import NoticesScheduler
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.scheduler_state import (
    SchedulerRegistry,
    SchedulerStateStore,
    SchedulerTaskDefinition,
    SchedulerTaskNotDeletable,
    SchedulerTaskState,
)
from src.infrastructure.subscriptions import SubscriptionStore

TZ = ZoneInfo("Asia/Shanghai")


def _definitions() -> tuple[SchedulerTaskDefinition, ...]:
    return (
        SchedulerTaskDefinition(
            id="dnaby_sign_daily",
            name="每日自动签到",
            schedule="daily@00:05",
        ),
        SchedulerTaskDefinition(
            id="dnaby_sign_cleanup",
            name="签到记录清理",
            schedule="daily@00:05",
            can_delete=False,
        ),
        SchedulerTaskDefinition(
            id="dnaby_mh_push",
            name="密函推送",
            schedule="hourly@00:30",
        ),
        SchedulerTaskDefinition(
            id="dnaby_ann_poll",
            name="公告轮询",
            schedule="interval@10m",
        ),
    )


def _register(registry: SchedulerRegistry) -> None:
    for definition in _definitions():
        registry.register(definition)


@pytest.mark.asyncio
async def test_registry_exposes_four_tasks_and_persists_irreversible_tombstone(
    tmp_path: Path,
) -> None:
    """三个业务任务可永久删除，维护清理任务拒绝删除且重启隐藏 tombstone。"""

    state_path = tmp_path / "scheduler_state.json"
    registry = SchedulerRegistry(state_path)
    _register(registry)
    await registry.initialize()

    assert {item.id for item in await registry.list_snapshots()} == {
        "dnaby_sign_daily",
        "dnaby_sign_cleanup",
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }

    with pytest.raises(SchedulerTaskNotDeletable):
        await registry.delete("dnaby_sign_cleanup")

    await registry.delete("dnaby_sign_daily")
    await registry.delete("dnaby_mh_push")
    await registry.delete("dnaby_ann_poll")
    assert {item.id for item in await registry.list_snapshots()} == {
        "dnaby_sign_cleanup"
    }

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(raw["deleted_tasks"]) == {
        "dnaby_sign_daily",
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }
    assert not hasattr(registry, "restore")

    restarted = SchedulerRegistry(state_path)
    _register(restarted)
    await restarted.initialize()
    assert [item.id for item in await restarted.list_snapshots()] == [
        "dnaby_sign_cleanup"
    ]


@pytest.mark.asyncio
async def test_tombstone_write_failure_restores_memory_and_keeps_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tombstone 原子写失败时不把任务误报为已删除，也不覆盖旧状态。"""

    state_path = tmp_path / "scheduler_state.json"
    state_path.write_text(json.dumps({"deleted_tasks": ["old-task"]}), encoding="utf-8")
    store = SchedulerStateStore(state_path)
    await store.load()

    def fail_save() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_unlocked", fail_save)
    with pytest.raises(OSError):
        await store.delete("new-task")

    assert await store.is_deleted("new-task") is False
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "deleted_tasks": ["old-task"],
    }


@pytest.mark.asyncio
async def test_registry_pause_resume_and_timezone_aware_next_run(
    tmp_path: Path,
) -> None:
    """暂停/恢复可观察，计划中的 next_run_at 必须带时区。"""

    registry = SchedulerRegistry(tmp_path / "scheduler_state.json")
    _register(registry)
    await registry.initialize()

    next_run = datetime(2026, 8, 29, 0, 5, tzinfo=TZ)
    await registry.activate("dnaby_sign_daily")
    await registry.set_next_run("dnaby_sign_daily", next_run)
    snapshot = await registry.get_snapshot("dnaby_sign_daily")
    assert snapshot is not None
    assert snapshot.state is SchedulerTaskState.RUNNING
    assert snapshot.next_run_at == next_run
    assert snapshot.next_run_at is not None
    assert snapshot.next_run_at.tzinfo is not None

    await registry.pause("dnaby_sign_daily")
    paused = await registry.get_snapshot("dnaby_sign_daily")
    assert paused is not None
    assert paused.state is SchedulerTaskState.PAUSED
    await registry.resume("dnaby_sign_daily")
    resumed = await registry.get_snapshot("dnaby_sign_daily")
    assert resumed is not None
    assert resumed.state is SchedulerTaskState.RUNNING


@pytest.mark.asyncio
async def test_scheduler_records_daily_next_run_and_error_state(tmp_path: Path) -> None:
    """签到 loop 睡眠前登记准确时间，执行异常进入 error 状态。"""

    registry = SchedulerRegistry(tmp_path / "scheduler_state.json")
    checkin_failed = asyncio.Event()
    sleep_entered = asyncio.Event()
    release_sleep = asyncio.Event()
    calls: list[float] = []

    class _FailingCheckin:
        async def auto_sign_all(self) -> str:
            checkin_failed.set()
            raise RuntimeError("upstream detail must not enter snapshot")

        async def clear_sign_records_before(self, record_date: date) -> int:
            return 0

    async def sleep(seconds: float) -> None:
        calls.append(seconds)
        sleep_entered.set()
        if len(calls) == 1:
            await release_sleep.wait()
            return
        await asyncio.Future()

    scheduler = SignScheduler(
        _FailingCheckin(),
        SubscriptionStore(tmp_path / "subscriptions.json"),
        registry=registry,
        sign_time="00:05",
        scheduled_enabled=True,
        enable_all_users=True,
        now=lambda: datetime(2026, 8, 28, 23, 59, 30, tzinfo=TZ),
        sleep=sleep,
    )
    await scheduler.start()
    await sleep_entered.wait()

    snapshot = await registry.get_snapshot("dnaby_sign_daily")
    assert snapshot is not None
    assert snapshot.next_run_at == datetime(2026, 8, 29, 0, 5, tzinfo=TZ)
    assert snapshot.next_run_at is not None
    assert snapshot.next_run_at.tzinfo is not None

    release_sleep.set()
    await checkin_failed.wait()
    await asyncio.sleep(0)
    errored = await registry.get_snapshot("dnaby_sign_daily")
    assert errored is not None
    assert errored.state is SchedulerTaskState.ERROR
    assert "upstream detail" not in (errored.last_error or "")

    await scheduler.stop()
    assert calls


@pytest.mark.asyncio
async def test_permanent_delete_prevents_notice_task_creation_after_restart(
    tmp_path: Path,
) -> None:
    """删除密函任务后，新的 NoticesScheduler 不再创建它。"""

    state_path = tmp_path / "scheduler_state.json"
    registry = SchedulerRegistry(state_path)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def sleep(_seconds: float) -> None:
        entered.set()
        await release.wait()

    class _Notices:
        async def push_mh_now(self) -> int:
            return 0

        async def poll_ann_now(self) -> int:
            return 0

    scheduler = NoticesScheduler(
        _Notices(),
        registry=registry,
        sleep=sleep,
    )
    await scheduler.start()
    await entered.wait()
    await scheduler.pause_task("dnaby_ann_poll")
    assert {task.get_name() for task in scheduler._tasks} == {"dnaby_mh_push"}
    await scheduler.resume_task("dnaby_ann_poll")
    assert {task.get_name() for task in scheduler._tasks} == {
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }
    await scheduler.delete_task("dnaby_mh_push")
    assert {task.get_name() for task in scheduler._tasks} == {"dnaby_ann_poll"}
    await scheduler.stop()

    restarted_registry = SchedulerRegistry(state_path)
    restarted = NoticesScheduler(
        _Notices(),
        registry=restarted_registry,
        sleep=sleep,
    )
    await restarted.start()
    assert {task.get_name() for task in restarted._tasks} == {"dnaby_ann_poll"}
    release.set()
    await restarted.stop()


@pytest.mark.asyncio
async def test_bootstrap_wires_one_shared_registry_and_state_path(
    tmp_path: Path,
) -> None:
    """runtime 将四个任务汇总到同一个运行期 scheduler_state.json。"""

    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=database,
    )

    registry = runtime.services["scheduler_registry"]
    assert isinstance(registry, SchedulerRegistry)
    sign_scheduler = runtime.services["sign_scheduler"]
    notices_scheduler = runtime.services["notices_scheduler"]
    assert isinstance(sign_scheduler, SignScheduler)
    assert isinstance(notices_scheduler, NoticesScheduler)
    assert sign_scheduler.registry is registry
    assert notices_scheduler.registry is registry
    assert registry.state_path == (tmp_path / "scheduler_state.json").resolve()
    assert {item.id for item in await registry.list_snapshots()} == {
        "dnaby_sign_daily",
        "dnaby_sign_cleanup",
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }
