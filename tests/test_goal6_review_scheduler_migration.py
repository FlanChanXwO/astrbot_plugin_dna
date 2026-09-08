"""PR #27 P2-1：legacy scheduled_enabled 只能一次性迁移为可恢复的暂停状态。"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from src.infrastructure.config import DnabySettings
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.scheduler_state import SchedulerRegistry, SchedulerTaskState
from src.infrastructure.subscriptions import SubscriptionStore


class _CheckinProbe:
    async def auto_sign_all(self) -> str:
        return "auto-sign"

    async def clear_sign_records_before(self, _record_date: date) -> int:
        return 0


async def _sleep_forever(_seconds: float) -> None:
    await asyncio.Event().wait()


def _build_scheduler(
    state_path: Path,
    settings: DnabySettings,
) -> SignScheduler:
    return SignScheduler(
        _CheckinProbe(),
        SubscriptionStore(state_path.parent / "subscriptions.json"),
        registry=SchedulerRegistry(state_path),
        sign_task_enabled=settings.sign_in.scheduler_enabled_for_runtime,
        sleep=_sleep_forever,
    )


@pytest.mark.asyncio
async def test_legacy_disabled_scheduler_migrates_once_and_can_resume(
    tmp_path: Path,
) -> None:
    """旧 false 首次暂停，正式恢复后不再被旧隐藏字段重新关闭。"""

    settings = DnabySettings.from_config({"sign_in": {"scheduled_enabled": False}})
    state_path = tmp_path / "scheduler_state.json"

    scheduler = _build_scheduler(state_path, settings)
    await scheduler.start()
    await asyncio.sleep(0)

    assert [task.get_name() for task in scheduler._tasks] == ["dnaby_sign_cleanup"]
    paused = await scheduler.registry.get_snapshot("dnaby_sign_daily")
    assert paused is not None
    assert paused.state is SchedulerTaskState.PAUSED

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["paused_tasks"] == ["dnaby_sign_daily"]
    assert raw["migrations"] == ["legacy_scheduled_enabled"]

    await scheduler.resume_task("dnaby_sign_daily")
    await asyncio.sleep(0)
    assert {task.get_name() for task in scheduler._tasks} == {
        "dnaby_sign_daily",
        "dnaby_sign_cleanup",
    }
    await scheduler.stop()

    restarted_settings = DnabySettings.from_config(
        {"sign_in": {"scheduled_enabled": False}}
    )
    restarted = _build_scheduler(state_path, restarted_settings)
    await restarted.start()
    await asyncio.sleep(0)
    assert {task.get_name() for task in restarted._tasks} == {
        "dnaby_sign_daily",
        "dnaby_sign_cleanup",
    }
    await restarted.stop()
