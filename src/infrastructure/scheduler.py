"""签到的 asyncio 计划任务与结果推送。

每日按 ``sign_time`` 执行一次全账号自动签到并推送结果给订阅者，每日按
``cleanup_time`` 清理过期的签到记录。任务在 ``start()`` 创建、``stop()`` 取消，
``initialize()/terminate()`` 通过生命周期钩子驱动；``sleep``/``now`` 可注入以便
离线测试，不依赖真实时钟。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..modules.checkin import messages
from .subscriptions import SubscriptionStore

TZ = ZoneInfo("Asia/Shanghai")
NowCallable = Callable[[], datetime]
SleepCallable = Callable[[float], Awaitable[None]]
PushCallable = Callable[[str, str], Awaitable[Any]]

_SIGN_TASK_NAME = "dnaby_sign_daily"
_CLEANUP_TASK_NAME = "dnaby_sign_cleanup"


class SchedulableCheckin(Protocol):
    """计划任务所需的签到接口。"""

    async def auto_sign_all(self) -> str: ...
    async def clear_sign_records_before(self, record_date: date) -> int: ...


def _parse_hhmm(value: Any, default: tuple[int, int] = (0, 5)) -> tuple[int, int]:
    try:
        if isinstance(value, (tuple, list)):
            hour, minute = int(value[0]), int(value[1])
        else:
            hour, minute = (int(x) for x in str(value).split(":"))
    except (ValueError, TypeError):
        hour, minute = default
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        hour, minute = default
    return hour, minute


def _next_daily(now: datetime, hour: int, minute: int) -> datetime:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


class SignScheduler:
    """管理每日签到与记录清理的 asyncio 任务。"""

    def __init__(
        self,
        checkin: SchedulableCheckin,
        subscriptions: SubscriptionStore,
        *,
        sign_time: tuple[int, int] = (0, 5),
        cleanup_time: tuple[int, int] = (0, 5),
        scheduled_enabled: bool = True,
        enable_all_users: bool = False,
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
        push: PushCallable | None = None,
    ) -> None:
        self.checkin = checkin
        self.subscriptions = subscriptions
        self.sign_time = _parse_hhmm(sign_time)
        self.cleanup_time = _parse_hhmm(cleanup_time)
        self.scheduled_enabled = scheduled_enabled
        self.enable_all_users = enable_all_users
        self._sleep = sleep
        self._now = now if now is not None else lambda: datetime.now(TZ)
        self._push = push
        self._tasks: list[asyncio.Task] = []
        self._started = False

    @property
    def started(self) -> bool:
        """返回计划任务是否已创建。"""

        return self._started

    async def _run_daily(self, name: str, coro: Callable[[], Awaitable[None]], hour: int, minute: int) -> None:
        while True:
            delay = (_next_daily(self._now(), hour, minute) - self._now()).total_seconds()
            await self._sleep(max(0.0, delay))
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                from astrbot.api import logger

                logger.warning(f"[dnaby][{name}] 定时任务异常: {error}")

    async def start(self) -> None:
        """幂等创建计划任务；重复 start 不创建重复任务。"""

        if self._started:
            return
        tasks: list[asyncio.Task] = []
        # 自动签到需要「定时开启 + 全部账号授权」；新 schema 没有 per-user 签到开关，
        # enable_all_users 承担 legacy SigninMaster 对全账号自动签到的门控语义。
        if self.scheduled_enabled and self.enable_all_users:
            tasks.append(
                asyncio.create_task(
                    self._run_daily(
                        "auto_sign",
                        self._on_sign_time,
                        *self.sign_time,
                    ),
                    name=_SIGN_TASK_NAME,
                )
            )
        tasks.append(
            asyncio.create_task(
                self._run_daily(
                    "clear_sign_record",
                    self._on_cleanup_time,
                    *self.cleanup_time,
                ),
                name=_CLEANUP_TASK_NAME,
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

    async def _on_sign_time(self) -> None:
        await self.run_sign_once()

    async def _on_cleanup_time(self) -> None:
        await self.run_cleanup_once()

    async def run_sign_once(self) -> str:
        """执行一次自动签到并把摘要推送给订阅者，返回摘要文本。"""

        text = await self.checkin.auto_sign_all()
        subscribers = await self.subscriptions.get(messages.SIGN_RESULT_SUBSCRIBE)
        for subscription in subscribers:
            if self._push is None:
                continue
            await self._push(subscription.unified_msg_origin, text)
        return text

    async def run_cleanup_once(self) -> int:
        """清理 2 天前的签到记录，返回删除条数。"""

        two_days_ago = self._now().date() - timedelta(days=2)
        return await self.checkin.clear_sign_records_before(two_days_ago)


__all__ = ["SignScheduler"]
