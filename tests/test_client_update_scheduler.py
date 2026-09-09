"""客户端更新 scheduler 的错误可观测性测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure import client_updates_scheduler as scheduler_module
from src.infrastructure.client_updates_scheduler import (
    CLIENT_UPDATE_TASK_ID,
    ClientUpdatesScheduler,
)


@pytest.mark.asyncio
async def test_scheduler_logs_exception_type_without_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Poller:
        async def poll_now(self):
            raise RuntimeError("response body contains secret-token")

    class Delivery:
        async def deliver(self, _changes):
            raise AssertionError("poll 失败后不应调用 delivery")

    class RecordingLogger:
        def __init__(self) -> None:
            self.calls: list[tuple[object, tuple[object, ...]]] = []

        def warning(self, message: object, *args: object) -> None:
            self.calls.append((message, args))

    async def stop_after_iteration(_seconds: float) -> None:
        raise asyncio.CancelledError

    logger = RecordingLogger()
    monkeypatch.setattr(scheduler_module, "logger", logger)
    scheduler = ClientUpdatesScheduler(
        Poller(),
        Delivery(),
        check_minutes=1,
        sleep=stop_after_iteration,
    )
    await scheduler.registry.resume(CLIENT_UPDATE_TASK_ID)

    with pytest.raises(asyncio.CancelledError):
        await scheduler._run_periodic()

    assert logger.calls == [
        (
            "[dnaby][dnaby_client_update_poll] 定时任务异常 error_type=%s",
            ("RuntimeError",),
        )
    ]
    assert "secret-token" not in repr(logger.calls)
