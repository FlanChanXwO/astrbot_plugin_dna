"""通知（密函/公告）的 asyncio 计划任务。

每小时在配置的分钟推送一次密函，按 ``poll_minutes`` 轮询公告并推送新条目。
任务在 ``start()`` 创建、``stop()`` 取消，``initialize()/terminate()`` 通过生命周期
钩子驱动；``sleep``/``now`` 可注入以便离线测试，不依赖真实时钟。推送失败由
``_run`` 记录日志，不静默。
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
NowCallable = Callable[[], datetime]
SleepCallable = Callable[[float], Awaitable[None]]

_MH_PUSH_TASK_NAME = "dnaby_mh_push"
_ANN_POLL_TASK_NAME = "dnaby_ann_poll"


class SchedulableNotices(Protocol):
    """计划任务所需的通知接口。"""

    async def push_mh_now(self) -> int: ...
    async def poll_ann_now(self) -> int: ...


def _next_hourly(now: datetime, minute: int, second: int) -> datetime:
    target = now.replace(minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(hours=1)
    return target


class NoticesScheduler:
    """管理每小时密函推送与周期性公告轮询的 asyncio 任务。"""

    def __init__(
        self,
        notices: SchedulableNotices,
        *,
        announcement_enabled: bool = True,
        poll_minutes: int = 10,
        push_minute: int = 0,
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
        registry: SchedulerRegistry | None = None,
    ) -> None:
        self.notices = notices
        self.announcement_enabled = announcement_enabled
        self.poll_minutes = max(1, int(poll_minutes))
        self.push_minute = int(push_minute)
        if not 0 <= self.push_minute <= 59:
            raise ValueError("密函推送分钟必须为 0--59")
        self._sleep = sleep
        self._now = now if now is not None else lambda: datetime.now(TZ)
        self.registry = registry or SchedulerRegistry()
        self._tasks: list[asyncio.Task] = []
        self._task_by_id: dict[str, asyncio.Task] = {}
        self._enabled_tasks = {
            _MH_PUSH_TASK_NAME: True,
            _ANN_POLL_TASK_NAME: self.announcement_enabled,
        }
        self._task_specs: dict[str, tuple[str, Callable[[], Awaitable[object]]]] = {
            _MH_PUSH_TASK_NAME: ("mh_push", self.notices.push_mh_now),
            _ANN_POLL_TASK_NAME: ("ann_poll", self.notices.poll_ann_now),
        }
        self.registry.register(
            SchedulerTaskDefinition(
                id=_MH_PUSH_TASK_NAME,
                name="密函推送",
                schedule=f"hourly@{self.push_minute:02d}:00",
                targets=("mh_subscriptions",),
            ),
            enabled=self._enabled_tasks[_MH_PUSH_TASK_NAME],
        )
        self.registry.register(
            SchedulerTaskDefinition(
                id=_ANN_POLL_TASK_NAME,
                name="公告轮询",
                schedule=f"interval@{self.poll_minutes}m",
                targets=("ann_subscriptions",),
            ),
            enabled=self._enabled_tasks[_ANN_POLL_TASK_NAME],
        )
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def push_time(self) -> tuple[int, int]:
        """返回配置的每小时触发点。"""

        return self.push_minute, 0

    async def _run_hourly(
        self,
        task_id: str,
        coro: Callable[[], Awaitable[object]],
    ) -> None:
        while True:
            now = self._now()
            next_run = _next_hourly(now, *self.push_time)
            await self.registry.set_next_run(task_id, next_run)
            delay = (next_run - now).total_seconds()
            await self._sleep(max(0.0, delay))
            snapshot = await self.registry.get_snapshot(task_id)
            if snapshot is None or snapshot.state is SchedulerTaskState.PAUSED:
                return
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await self.registry.mark_error(task_id)
                logger.warning(f"[dnaby][{_MH_PUSH_TASK_NAME}] 定时任务异常")
            else:
                await self.registry.mark_running(task_id)

    async def _run_periodic(
        self,
        task_id: str,
        coro: Callable[[], Awaitable[object]],
    ) -> None:
        while True:
            now = self._now()
            next_run = now + timedelta(minutes=self.poll_minutes)
            await self.registry.set_next_run(task_id, next_run)
            await self._sleep(self.poll_minutes * 60)
            snapshot = await self.registry.get_snapshot(task_id)
            if snapshot is None or snapshot.state is SchedulerTaskState.PAUSED:
                return
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await self.registry.mark_error(task_id)
                logger.warning(f"[dnaby][{_ANN_POLL_TASK_NAME}] 定时任务异常")
            else:
                await self.registry.mark_running(task_id)

    def _create_task(self, task_id: str) -> asyncio.Task:
        if task_id in self._task_by_id:
            return self._task_by_id[task_id]
        if not self._enabled_tasks[task_id]:
            raise ValueError(f"任务当前配置未启用: {task_id}")
        _name, coro = self._task_specs[task_id]
        if task_id == _MH_PUSH_TASK_NAME:
            task = asyncio.create_task(
                self._run_hourly(task_id, coro),
                name=task_id,
            )
        else:
            task = asyncio.create_task(
                self._run_periodic(task_id, coro),
                name=task_id,
            )
        self._tasks.append(task)
        self._task_by_id[task_id] = task
        return task

    async def _cancel_task(self, task_id: str) -> None:
        task = self._task_by_id.pop(task_id, None)
        if task is None:
            return
        if task in self._tasks:
            self._tasks.remove(task)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def start(self) -> None:
        """幂等创建计划任务；重复 start 不创建重复任务。"""

        await self.registry.initialize()
        if self._started:
            return
        for task_id, enabled in self._enabled_tasks.items():
            if not enabled or await self.registry.is_deleted(task_id):
                continue
            await self.registry.activate(task_id)
            self._create_task(task_id)
        self._started = True

    async def stop(self) -> None:
        """取消全部计划任务并等待其退出；重复 stop 幂等。"""

        active_ids = tuple(self._task_by_id)
        tasks, self._tasks = self._tasks, []
        self._task_by_id = {}
        self._started = False
        if not tasks:
            return
        for task_id in active_ids:
            await self.registry.deactivate(task_id)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def pause_task(self, task_id: str) -> None:
        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.pause(task_id)
        await self._cancel_task(task_id)

    async def resume_task(self, task_id: str) -> None:
        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.resume(task_id)
        if self._started:
            self._create_task(task_id)

    async def delete_task(self, task_id: str) -> None:
        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.delete(task_id)
        await self._cancel_task(task_id)

    async def update_task(self, task_id: str, schedule: str) -> str:
        """更新现有通知任务参数，并立即重建运行中的 loop。"""

        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        normalized, values = parse_scheduler_schedule(task_id, schedule)
        if task_id == _MH_PUSH_TASK_NAME:
            if not isinstance(values, tuple):
                raise ValueError("密函任务 schedule 类型错误")
            self.push_minute = values[0]
        else:
            if not isinstance(values, int):
                raise ValueError("公告任务 schedule 类型错误")
        await self.registry.update_definition(task_id, schedule=normalized)
        if task_id != _MH_PUSH_TASK_NAME:
            self.poll_minutes = cast(int, values)

        snapshot = await self.registry.get_snapshot(task_id)
        if (
            self._started
            and snapshot is not None
            and snapshot.state is not SchedulerTaskState.PAUSED
            and self._enabled_tasks[task_id]
        ):
            await self._cancel_task(task_id)
            self._create_task(task_id)
        return normalized

    async def pause(self, task_id: str) -> None:
        await self.pause_task(task_id)

    async def resume(self, task_id: str) -> None:
        await self.resume_task(task_id)

    async def delete(self, task_id: str) -> None:
        await self.delete_task(task_id)


__all__ = ["NoticesScheduler"]
