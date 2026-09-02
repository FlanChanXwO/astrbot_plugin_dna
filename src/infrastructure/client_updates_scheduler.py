"""客户端更新的独立 asyncio 计划任务。

客户端更新与公告使用同一个 ``SchedulerRegistry`` 保存任务状态，但由独立的
scheduler 管理自己的任务、周期和生命周期，避免修改公告配置或任务状态。轮询
异常会标记为安全的 ``error`` 状态并保留日志可观测性，不把上游异常原文写入
registry。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from astrbot.api import logger

from .scheduler_state import (
    SchedulerRegistry,
    SchedulerTaskDefinition,
    SchedulerTaskNotFound,
    SchedulerTaskState,
    parse_scheduler_schedule,
)

TZ = ZoneInfo("Asia/Shanghai")
CLIENT_UPDATE_TASK_ID = "dnaby_client_update_poll"
CLIENT_UPDATE_TASK_NAME = "客户端更新轮询"
CLIENT_UPDATE_TARGET = "client_update_subscriptions"
DEFAULT_CLIENT_UPDATE_CHECK_MINUTES = 60

NowCallable = Callable[[], datetime]
SleepCallable = Callable[[float], Awaitable[None]]


class SchedulableClientUpdates(Protocol):
    """计划任务所需的客户端更新轮询接口。"""

    async def poll_now(self) -> int: ...


class ClientUpdatesScheduler:
    """管理唯一的客户端更新轮询任务。"""

    def __init__(
        self,
        client_updates: SchedulableClientUpdates,
        *,
        enabled: bool = True,
        check_minutes: int = DEFAULT_CLIENT_UPDATE_CHECK_MINUTES,
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
        registry: SchedulerRegistry | None = None,
    ) -> None:
        self.client_updates = client_updates
        self.enabled = bool(enabled)
        self.check_minutes = _validate_check_minutes(check_minutes)
        self._sleep = sleep
        self._now = now if now is not None else lambda: datetime.now(TZ)
        self.registry = registry or SchedulerRegistry()
        self._tasks: list[asyncio.Task] = []
        self._task_by_id: dict[str, asyncio.Task] = {}
        self.registry.register(
            SchedulerTaskDefinition(
                id=CLIENT_UPDATE_TASK_ID,
                name=CLIENT_UPDATE_TASK_NAME,
                schedule=f"interval@{self.check_minutes}m",
                targets=(CLIENT_UPDATE_TARGET,),
            ),
            enabled=self.enabled,
        )
        self._started = False

    @property
    def started(self) -> bool:
        """返回 scheduler 是否已经完成启动。"""

        return self._started

    async def _run_periodic(self) -> None:
        while True:
            now = self._now()
            next_run = now + timedelta(minutes=self.check_minutes)
            await self.registry.set_next_run(CLIENT_UPDATE_TASK_ID, next_run)
            await self._sleep(self.check_minutes * 60)
            snapshot = await self.registry.get_snapshot(CLIENT_UPDATE_TASK_ID)
            if snapshot is None or snapshot.state is SchedulerTaskState.PAUSED:
                return
            try:
                await self.client_updates.poll_now()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await self.registry.mark_error(CLIENT_UPDATE_TASK_ID)
                logger.warning(f"[dnaby][{CLIENT_UPDATE_TASK_ID}] 定时任务异常")
            else:
                await self.registry.mark_running(CLIENT_UPDATE_TASK_ID)

    def _create_task(self) -> asyncio.Task:
        existing = self._task_by_id.get(CLIENT_UPDATE_TASK_ID)
        if existing is not None:
            return existing
        if not self.enabled:
            raise ValueError("任务当前配置未启用: dnaby_client_update_poll")
        task = asyncio.create_task(
            self._run_periodic(),
            name=CLIENT_UPDATE_TASK_ID,
        )
        self._tasks.append(task)
        self._task_by_id[CLIENT_UPDATE_TASK_ID] = task
        return task

    async def _cancel_task(self) -> None:
        task = self._task_by_id.pop(CLIENT_UPDATE_TASK_ID, None)
        if task is None:
            return
        if task in self._tasks:
            self._tasks.remove(task)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def start(self) -> None:
        """幂等创建客户端更新任务并激活 registry。"""

        await self.registry.initialize()
        if self._started:
            return
        if self.enabled and not await self.registry.is_deleted(CLIENT_UPDATE_TASK_ID):
            await self.registry.activate(CLIENT_UPDATE_TASK_ID)
            self._create_task()
        self._started = True

    async def stop(self) -> None:
        """取消客户端更新任务并等待其退出；重复 stop 幂等。"""

        task = self._task_by_id.get(CLIENT_UPDATE_TASK_ID)
        self._started = False
        if task is None:
            return
        await self.registry.deactivate(CLIENT_UPDATE_TASK_ID)
        await self._cancel_task()

    async def pause_task(self, task_id: str) -> None:
        if task_id != CLIENT_UPDATE_TASK_ID:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.pause(task_id)
        await self._cancel_task()

    async def resume_task(self, task_id: str) -> None:
        if task_id != CLIENT_UPDATE_TASK_ID:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.resume(task_id)
        if self._started:
            self._create_task()

    async def delete_task(self, task_id: str) -> None:
        if task_id != CLIENT_UPDATE_TASK_ID:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.delete(task_id)
        await self._cancel_task()

    async def update_task(self, task_id: str, schedule: str) -> str:
        """更新客户端检查周期，并立即重建运行中的 loop。"""

        if task_id != CLIENT_UPDATE_TASK_ID:
            raise SchedulerTaskNotFound(task_id)
        normalized, values = parse_scheduler_schedule(task_id, schedule)
        if not isinstance(values, int):
            raise TypeError("客户端更新任务 schedule 类型错误")
        await self.registry.update_definition(task_id, schedule=normalized)
        self.check_minutes = cast(int, values)

        snapshot = await self.registry.get_snapshot(task_id)
        if (
            self._started
            and snapshot is not None
            and snapshot.state is not SchedulerTaskState.PAUSED
            and self.enabled
        ):
            await self._cancel_task()
            self._create_task()
        return normalized

    async def pause(self, task_id: str) -> None:
        await self.pause_task(task_id)

    async def resume(self, task_id: str) -> None:
        await self.resume_task(task_id)

    async def delete(self, task_id: str) -> None:
        await self.delete_task(task_id)


def _validate_check_minutes(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("客户端更新检查间隔必须为正整数")
    return value


__all__ = [
    "CLIENT_UPDATE_TARGET",
    "CLIENT_UPDATE_TASK_ID",
    "CLIENT_UPDATE_TASK_NAME",
    "DEFAULT_CLIENT_UPDATE_CHECK_MINUTES",
    "ClientUpdatesScheduler",
    "SchedulableClientUpdates",
]
