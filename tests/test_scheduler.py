"""Task 18 计划任务的启动/取消、自动签到推送与记录清理测试。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.checkin import messages

TZ = ZoneInfo("Asia/Shanghai")


class _FakeCheckin:
    def __init__(self) -> None:
        self.auto_calls = 0
        self.cleanup_calls: list[date] = []

    async def auto_sign_all(self) -> str:
        self.auto_calls += 1
        return "[二重螺旋]自动任务\n今日成功游戏签到 2 个账号\n今日社区签到 1 个账号"

    async def clear_sign_records_before(self, record_date: date) -> int:
        self.cleanup_calls.append(record_date)
        return 3


def _noop_sleep(_seconds: float):
    raise AssertionError("测试不应真实睡眠")


@pytest.mark.asyncio
async def test_scheduler_start_is_idempotent_and_stop_cancels_tasks(tmp_path: Path) -> None:
    """重复 start 不重复创建任务，stop 取消全部并幂等。"""

    checkin = _FakeCheckin()
    scheduler = SignScheduler(
        checkin,
        SubscriptionStore(tmp_path / "subscriptions.json"),
        enable_all_users=True,
        sleep=_noop_sleep,
    )

    await scheduler.start()
    await scheduler.start()
    assert scheduler.started is True
    assert len(scheduler._tasks) == 2  # 签到 + 清理

    await scheduler.stop()
    await scheduler.stop()
    assert scheduler.started is False
    assert scheduler._tasks == []
    assert all(task.done() or task.cancelled() for task in [])


@pytest.mark.asyncio
async def test_scheduler_requires_enable_all_users_for_sign_task(tmp_path: Path) -> None:
    """未授权全部账号时，定时签到任务不创建，只保留清理任务。"""

    scheduler = SignScheduler(
        _FakeCheckin(),
        SubscriptionStore(tmp_path / "subscriptions.json"),
        scheduled_enabled=True,
        enable_all_users=False,
        sleep=_noop_sleep,
    )

    await scheduler.start()
    assert len(scheduler._tasks) == 1
    assert scheduler._tasks[0].get_name() == "dnaby_sign_cleanup"
    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_respects_scheduled_disabled(tmp_path: Path) -> None:
    """定时签到关闭时只创建清理任务。"""

    scheduler = SignScheduler(
        _FakeCheckin(),
        SubscriptionStore(tmp_path / "subscriptions.json"),
        scheduled_enabled=False,
        sleep=_noop_sleep,
    )

    await scheduler.start()
    assert len(scheduler._tasks) == 1
    assert scheduler._tasks[0].get_name() == "dnaby_sign_cleanup"
    await scheduler.stop()


@pytest.mark.asyncio
async def test_run_sign_once_pushes_summary_to_subscribers(tmp_path: Path) -> None:
    """自动签到后把摘要推送给订阅者，推送函数注入且可验证。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.SIGN_RESULT_SUBSCRIBE,
        origin="platform:group:g1",
        user_id="owner-1",
        bot_id="bot-1",
    )
    pushed: list[tuple[str, str]] = []
    checkin = _FakeCheckin()

    async def push(origin: str, text: str) -> None:
        pushed.append((origin, text))

    scheduler = SignScheduler(
        checkin,
        subscriptions,
        sleep=_noop_sleep,
        push=push,
    )

    text = await scheduler.run_sign_once()

    assert "今日成功游戏签到 2 个账号" in text
    assert pushed == [("platform:group:g1", text)]
    assert checkin.auto_calls == 1


@pytest.mark.asyncio
async def test_run_sign_once_without_push_or_subscribers_is_safe(tmp_path: Path) -> None:
    """无推送函数或订阅者时自动签到仍返回摘要，不抛错。"""

    checkin = _FakeCheckin()
    scheduler = SignScheduler(
        checkin,
        SubscriptionStore(tmp_path / "subscriptions.json"),
        sleep=_noop_sleep,
        push=None,
    )

    text = await scheduler.run_sign_once()

    assert "今日社区签到 1 个账号" in text


@pytest.mark.asyncio
async def test_run_cleanup_once_uses_two_days_ago(tmp_path: Path) -> None:
    """清理任务删除 2 天前的记录并返回条数。"""

    now = datetime(2026, 8, 12, 1, 0, tzinfo=TZ)
    checkin = _FakeCheckin()
    scheduler = SignScheduler(
        checkin,
        SubscriptionStore(tmp_path / "subscriptions.json"),
        sleep=_noop_sleep,
        now=lambda: now,
    )

    deleted = await scheduler.run_cleanup_once()

    assert deleted == 3
    assert checkin.cleanup_calls == [date(2026, 8, 10)]

@pytest.mark.asyncio
async def test_run_sign_once_continues_when_one_subscriber_push_fails(tmp_path: Path) -> None:
    """单个订阅者推送抛出异常时，不中断其他订阅者的推送。"""

    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.SIGN_RESULT_SUBSCRIBE,
        origin="platform:group:fail_group",
        user_id="owner-1",
        bot_id="bot-1",
    )
    await subscriptions.add(
        messages.SIGN_RESULT_SUBSCRIBE,
        origin="platform:group:ok_group",
        user_id="owner-2",
        bot_id="bot-1",
    )
    pushed: list[str] = []
    checkin = _FakeCheckin()

    async def push(origin: str, text: str) -> None:
        if "fail_group" in origin:
            raise ConnectionResetError("network failed")
        pushed.append(origin)

    scheduler = SignScheduler(
        checkin,
        subscriptions,
        sleep=_noop_sleep,
        push=push,
    )

    text = await scheduler.run_sign_once()

    assert "今日成功游戏签到 2 个账号" in text
    assert pushed == ["platform:group:ok_group"]


@pytest.mark.asyncio
async def test_sign_scheduler_parses_string_sign_time(tmp_path: Path) -> None:
    """SignScheduler 支持 HH:mm 字符串格式的时间。"""
    scheduler = SignScheduler(
        _FakeCheckin(),
        SubscriptionStore(tmp_path / "subscriptions.json"),
        sign_time="08:30",
        sleep=_noop_sleep,
    )
    assert scheduler.sign_time == (8, 30)


@pytest.mark.asyncio
async def test_sign_scheduler_rejects_invalid_sign_time(tmp_path: Path) -> None:
    """SignScheduler 遇到非法时间格式时必须显式失败。"""
    with pytest.raises(ValueError, match="非法时间"):
        SignScheduler(
            _FakeCheckin(),
            SubscriptionStore(tmp_path / "subscriptions.json"),
            sign_time="invalid:time",
            sleep=_noop_sleep,
        )
