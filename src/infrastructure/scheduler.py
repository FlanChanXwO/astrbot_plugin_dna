"""签到的 asyncio 计划任务与结果推送。

每日按 ``sign_time`` 执行一次全账号自动签到并推送结果给订阅者，每日按
``cleanup_time`` 清理过期的签到记录。任务在 ``start()`` 创建、``stop()`` 取消，
``initialize()/terminate()`` 通过生命周期钩子驱动；``sleep``/``now`` 可注入以便
离线测试，不依赖真实时钟。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..modules.checkin import messages
from ..modules.checkin.contracts import AutoSignReport, GroupSignReport
from .scheduler_state import (
    SchedulerRegistry,
    SchedulerTaskDefinition,
    SchedulerTaskNotFound,
    SchedulerTaskState,
    parse_scheduler_schedule,
)
from .subscriptions import SubscriptionStore

TZ = ZoneInfo("Asia/Shanghai")
NowCallable = Callable[[], datetime]
SleepCallable = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SignPushPayload:
    """推送适配器接收的签到消息；图片存在时附带明细文本。"""

    text: str
    image_bytes: bytes | None = None
    detail_text: str = ""


PushCallable = Callable[[str, SignPushPayload], Awaitable[Any]]

_SIGN_TASK_NAME = "dnaby_sign_daily"
_CLEANUP_TASK_NAME = "dnaby_sign_cleanup"


class SchedulableCheckin(Protocol):
    """计划任务所需的签到接口。"""

    async def auto_sign_report(
        self,
        *,
        group_ids: Collection[str] | None = None,
    ) -> AutoSignReport: ...
    async def clear_sign_records_before(self, record_date: date) -> int: ...


def _parse_hhmm(value: Any) -> tuple[int, int]:
    # 调度器构造阶段拒绝非法时间，避免后台任务悄悄以默认时刻启动。
    try:
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                raise ValueError("时分值必须包含小时和分钟")
            hour, minute = int(value[0]), int(value[1])
        else:
            parts = str(value).split(":")
            if len(parts) != 2:
                raise ValueError("时间必须包含小时和分钟")
            hour, minute = (int(x) for x in parts)
    except (ValueError, TypeError) as error:
        raise ValueError("非法时间格式，必须为 HH:mm") from error
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("非法时间范围，必须为 00:00-23:59")
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
        sign_time: str | tuple[int, int] = "00:05",
        cleanup_time: tuple[int, int] = (0, 5),
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
        push: PushCallable | None = None,
        registry: SchedulerRegistry | None = None,
        sign_task_enabled: bool = True,
    ) -> None:
        self.checkin = checkin
        self.subscriptions = subscriptions
        self.sign_time = _parse_hhmm(sign_time)
        self.cleanup_time = _parse_hhmm(cleanup_time)
        self._sleep = sleep
        self._now = now if now is not None else lambda: datetime.now(TZ)
        self._push = push
        self.registry = registry or SchedulerRegistry()
        self._tasks: list[asyncio.Task] = []
        self._task_by_id: dict[str, asyncio.Task] = {}
        # 旧 scheduled_enabled 只在首次启动时迁移为 registry 的暂停状态；
        # 具体 UID 是否签到仍由 AccountBinding.auto_sign_enabled 决定。
        self._legacy_scheduler_enabled = sign_task_enabled
        self._enabled_tasks = {
            _SIGN_TASK_NAME: True,
            _CLEANUP_TASK_NAME: True,
        }
        self._task_specs: dict[
            str,
            tuple[str, Callable[[], Awaitable[None]], tuple[int, int]],
        ] = {
            _SIGN_TASK_NAME: ("auto_sign", self._on_sign_time, self.sign_time),
            _CLEANUP_TASK_NAME: (
                "clear_sign_record",
                self._on_cleanup_time,
                self.cleanup_time,
            ),
        }
        self.registry.register(
            SchedulerTaskDefinition(
                id=_SIGN_TASK_NAME,
                name="每日自动签到",
                schedule=f"daily@{self.sign_time[0]:02d}:{self.sign_time[1]:02d}",
                targets=(
                    "sign_result_subscriptions",
                    "sign_group_report_subscriptions",
                ),
            ),
            enabled=self._enabled_tasks[_SIGN_TASK_NAME],
        )
        self.registry.register(
            SchedulerTaskDefinition(
                id=_CLEANUP_TASK_NAME,
                name="签到记录清理",
                schedule=f"daily@{self.cleanup_time[0]:02d}:{self.cleanup_time[1]:02d}",
                targets=("sign_records",),
                can_delete=False,
            ),
            enabled=self._enabled_tasks[_CLEANUP_TASK_NAME],
        )
        self._started = False

    @property
    def started(self) -> bool:
        """返回计划任务是否已创建。"""

        return self._started

    async def _run_daily(
        self,
        task_id: str,
        name: str,
        coro: Callable[[], Awaitable[None]],
        hour: int,
        minute: int,
    ) -> None:
        while True:
            now = self._now()
            next_run = _next_daily(now, hour, minute)
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
                from astrbot.api import logger

                logger.warning(f"[dnaby][{name}] 定时任务异常")
            else:
                await self.registry.mark_running(task_id)
            # 执行完成后增加小余量，防止微秒级时钟抖动在同一目标分钟内重复触发
            await self._sleep(1.0)

    def _create_task(self, task_id: str) -> asyncio.Task:
        if task_id in self._task_by_id:
            return self._task_by_id[task_id]
        if not self._enabled_tasks[task_id]:
            raise ValueError(f"任务当前配置未启用: {task_id}")
        name, coro, (hour, minute) = self._task_specs[task_id]
        task = asyncio.create_task(
            self._run_daily(task_id, name, coro, hour, minute),
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
        await self.registry.migrate_legacy_sign_scheduler(
            enabled=self._legacy_scheduler_enabled,
        )
        # 签到任务始终存在；CheckinService 会按每个 UID 的个人开关筛选候选。
        for task_id, enabled in self._enabled_tasks.items():
            if (
                not enabled
                or await self.registry.is_deleted(task_id)
                or await self.registry.is_paused(task_id)
            ):
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
        """暂停一个归属本 scheduler 的任务。"""

        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.pause(task_id)
        await self._cancel_task(task_id)

    async def resume_task(self, task_id: str) -> None:
        """恢复一个归属本 scheduler 的任务。"""

        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.resume(task_id)
        if self._started:
            self._create_task(task_id)

    async def delete_task(self, task_id: str) -> None:
        """永久删除一个归属本 scheduler 的业务任务。"""

        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        await self.registry.delete(task_id)
        await self._cancel_task(task_id)

    async def update_task(self, task_id: str, schedule: str) -> str:
        """更新现有每日任务时间，并立即重建运行中的 loop。"""

        if task_id not in self._task_specs:
            raise SchedulerTaskNotFound(task_id)
        normalized, values = parse_scheduler_schedule(task_id, schedule)
        if not isinstance(values, tuple):
            raise TypeError("签到任务 schedule 类型错误")

        await self.registry.update_definition(task_id, schedule=normalized)
        name, coro, _old_values = self._task_specs[task_id]
        self._task_specs[task_id] = (name, coro, values)
        if task_id == _SIGN_TASK_NAME:
            self.sign_time = values
        else:
            self.cleanup_time = values

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

    async def _on_sign_time(self) -> None:
        await self.run_sign_once()

    async def _on_cleanup_time(self) -> None:
        await self.run_cleanup_once()

    async def _push_payload(self, origin: str, payload: SignPushPayload) -> None:
        """推送单个目标；单个目标失败不影响其他目标。"""

        if self._push is None:
            return
        try:
            result = self._push(origin, payload)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning("[dnaby][sign_push] 推送失败")

    @staticmethod
    def _group_payload(report: GroupSignReport) -> SignPushPayload:
        """把一类群报告转换为推送层 payload。"""

        text = "\n".join(
            part for part in (report.summary_text, report.detail_text) if part
        )
        return SignPushPayload(
            text=text,
            image_bytes=report.image_bytes,
            detail_text=report.detail_text,
        )

    async def run_sign_once(self) -> str:
        """执行一次自动签到，分别推送全局汇总和本群报告。"""

        try:
            group_subscribers = await self.subscriptions.get(
                messages.SIGN_GROUP_REPORT_SUBSCRIBE
            )
        except RuntimeError:
            # 订阅是通知设施；存储异常不能阻止本次核心签到执行。
            await self.checkin.auto_sign_report(group_ids=frozenset())
            raise
        target_group_ids = frozenset(
            subscription.group_id
            for subscription in group_subscribers
            if subscription.group_id
        )
        report = await self.checkin.auto_sign_report(
            group_ids=target_group_ids,
        )
        global_payload = SignPushPayload(text=report.summary_text)
        global_subscribers = await self.subscriptions.get(
            messages.SIGN_RESULT_SUBSCRIBE
        )
        for subscription in global_subscribers:
            await self._push_payload(
                subscription.unified_msg_origin,
                global_payload,
            )

        for subscription in group_subscribers:
            group_reports = report.group_reports.get(subscription.group_id, ())
            for group_report in group_reports:
                await self._push_payload(
                    subscription.unified_msg_origin,
                    self._group_payload(group_report),
                )
        return report.summary_text

    async def run_cleanup_once(self) -> int:
        """清理 2 天前的签到记录，返回删除条数。"""

        two_days_ago = self._now().date() - timedelta(days=2)
        return await self.checkin.clear_sign_records_before(two_days_ago)


__all__ = ["SignPushPayload", "SignScheduler"]
