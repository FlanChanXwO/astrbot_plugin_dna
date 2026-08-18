"""Task 22 NoticesScheduler 的计划任务启动/取消测试。"""

from __future__ import annotations

import pytest

from src.infrastructure.notices_scheduler import NoticesScheduler


class _FakeNotices:
    def __init__(self) -> None:
        self.push_calls = 0
        self.poll_calls = 0

    async def push_mh_now(self) -> int:
        self.push_calls += 1
        return 1

    async def poll_ann_now(self) -> int:
        self.poll_calls += 1
        return 0


def _noop_sleep(_seconds: float):
    raise AssertionError("测试不应真实睡眠")


@pytest.mark.asyncio
async def test_notices_scheduler_start_stop_is_idempotent() -> None:
    """重复 start 不重复创建任务，stop 取消全部并幂等。"""

    scheduler = NoticesScheduler(_FakeNotices(), sleep=_noop_sleep)

    await scheduler.start()
    await scheduler.start()
    assert scheduler.started is True
    assert {task.get_name() for task in scheduler._tasks} == {
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }

    await scheduler.stop()
    await scheduler.stop()
    assert scheduler.started is False
    assert scheduler._tasks == []


@pytest.mark.asyncio
async def test_notices_scheduler_task_names_and_config() -> None:
    """任务名稳定且 push_time/poll_minutes 被解析。"""

    scheduler = NoticesScheduler(
        _FakeNotices(),
        push_time="25:99",  # 越界 → 回落默认 0:30
        poll_minutes=5,
        sleep=_noop_sleep,
    )

    assert scheduler.push_time == (0, 30)
    assert scheduler.poll_minutes == 5
