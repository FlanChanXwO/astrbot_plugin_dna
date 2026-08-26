"""通知（密函/公告）的 asyncio 计划任务。

每小时按 ``push_time`` 推送一次密函，按 ``poll_minutes`` 轮询公告并推送新条目。
任务在 ``start()`` 创建、``stop()`` 取消，``initialize()/terminate()`` 通过生命周期
钩子驱动；``sleep``/``now`` 可注入以便离线测试，不依赖真实时钟。推送失败由
``_run`` 记录日志，不静默。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from astrbot.api import logger

TZ = ZoneInfo("Asia/Shanghai")
NowCallable = Callable[[], datetime]
SleepCallable = Callable[[float], Awaitable[None]]

_MH_PUSH_TASK_NAME = "dnaby_mh_push"
_ANN_POLL_TASK_NAME = "dnaby_ann_poll"


class SchedulableNotices(Protocol):
    """计划任务所需的通知接口。"""

    async def push_mh_now(self) -> int: ...
    async def poll_ann_now(self) -> int: ...


def _parse_hhmm(value: object, default: tuple[int, int] = (0, 30)) -> tuple[int, int]:
    try:
        if isinstance(value, (tuple, list)):
            minute, second = int(value[0]), int(value[1])
        else:
            minute, second = (int(x) for x in str(value).split(":"))
    except (ValueError, TypeError):
        minute, second = default
    if minute < 0 or minute > 59 or second < 0 or second > 59:
        minute, second = default
    return minute, second


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
        push_time: str | tuple[int, int] = (0, 30),
        poll_minutes: int = 10,
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
    ) -> None:
        self.notices = notices
        self.announcement_enabled = announcement_enabled
        self.push_time = _parse_hhmm(push_time)
        self.poll_minutes = max(1, int(poll_minutes))
        self._sleep = sleep
        self._now = now if now is not None else lambda: datetime.now(TZ)
        self._tasks: list[asyncio.Task] = []
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def _run_hourly(self, coro: Callable[[], Awaitable[object]]) -> None:
        while True:
            delay = (_next_hourly(self._now(), *self.push_time) - self._now()).total_seconds()
            await self._sleep(max(0.0, delay))
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.warning(f"[dnaby][{_MH_PUSH_TASK_NAME}] 定时任务异常: {error}")
            # 执行完成后增加小余量，防止微秒级时钟抖动在同一目标秒内重复触发
            await self._sleep(1.0)

    async def _run_periodic(self, coro: Callable[[], Awaitable[object]]) -> None:
        while True:
            await self._sleep(self.poll_minutes * 60)
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.warning(f"[dnaby][{_ANN_POLL_TASK_NAME}] 定时任务异常: {error}")

    async def start(self) -> None:
        """幂等创建计划任务；重复 start 不创建重复任务。"""

        if self._started:
            return
        tasks: list[asyncio.Task] = [
            asyncio.create_task(
                self._run_hourly(self.notices.push_mh_now),
                name=_MH_PUSH_TASK_NAME,
            ),
        ]
        if self.announcement_enabled:
            tasks.append(
                asyncio.create_task(
                    self._run_periodic(self.notices.poll_ann_now),
                    name=_ANN_POLL_TASK_NAME,
                )
            )
        self._tasks = tasks
        self._started = True

    async def stop(self) -> None:
        """取消全部计划任务并等待其退出；重复 stop 幂等。"""

        tasks, self._tasks = self._tasks, []
        self._started = False
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["NoticesScheduler"]
