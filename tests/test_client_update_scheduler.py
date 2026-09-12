"""客户端更新 scheduler 的错误可观测性测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.client_updates_scheduler import (
    CLIENT_UPDATE_TASK_ID,
    ClientUpdatesScheduler,
)
from src.infrastructure.scheduler_state import SchedulerTaskState


@pytest.mark.asyncio
async def test_scheduler_logs_exception_type_without_exception_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Poller:
        async def poll_now(self):
            raise RuntimeError("response body contains secret-token")

    class Delivery:
        def __init__(self) -> None:
            self.calls = 0

        async def deliver(self, _changes):
            self.calls += 1
            return 0

    async def stop_after_iteration(_seconds: float) -> None:
        raise asyncio.CancelledError

    delivery = Delivery()
    scheduler = ClientUpdatesScheduler(
        Poller(),
        delivery,
        check_minutes=1,
        sleep=stop_after_iteration,
    )
    await scheduler.registry.resume(CLIENT_UPDATE_TASK_ID)

    with (
        caplog.at_level("WARNING", logger="astrbot"),
        pytest.raises(asyncio.CancelledError),
    ):
        await scheduler._run_periodic()

    snapshot = await scheduler.registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
    assert snapshot is not None
    assert snapshot.state is SchedulerTaskState.ERROR
    assert delivery.calls == 0
    assert "RuntimeError" in caplog.text
    assert "secret-token" not in caplog.text
