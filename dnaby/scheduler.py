"""定时任务（asyncio 循环，替代 gsucore APScheduler）。

- 每日签到：SignTime（DNAUID签到配置）→ ``dna_auto_sign``
- 每日 00:05：清理 2 天前签到记录 → ``clear_dna_sign_record``
- 每小时 MHPushSubscribe(分钟:秒)：密函推送 → ``dna_push_mh_notify``
- 每 AnnMinuteCheck 分钟：公告轮询 → ``check_dna_ann_state``

由 main.py 在 ``initialize()`` 启动、``terminate()`` 取消。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astrbot.api import logger

TZ = ZoneInfo("Asia/Shanghai")


def _parse_hhmm(value, default_h: int = 0, default_m: int = 5) -> tuple[int, int]:
    try:
        if isinstance(value, (tuple, list)):
            h, m = int(value[0]), int(value[1])
        else:
            h, m = (int(x) for x in str(value).split(":"))
    except (ValueError, TypeError):
        h, m = default_h, default_m
    if h < 0 or h > 23 or m < 0 or m > 59:
        h, m = default_h, default_m
    return h, m


def _next_daily(hour: int, minute: int) -> datetime:
    now = datetime.now(TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _next_hourly(mm: int, ss: int) -> datetime:
    now = datetime.now(TZ)
    target = now.replace(minute=mm, second=ss, microsecond=0)
    if target <= now:
        target += timedelta(hours=1)
    return target


async def _run_loop(name: str, coro_factory, delay_seconds: float) -> None:
    """按固定间隔执行。delay_seconds 为两次执行间隔。"""
    while True:
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[dnaby][{name}] 定时任务异常: {e}")
        await asyncio.sleep(delay_seconds)


async def _run_daily(name: str, coro_factory, hour: int, minute: int) -> None:
    """每天 hour:minute 执行一次。"""
    while True:
        await asyncio.sleep((_next_daily(hour, minute) - datetime.now(TZ)).total_seconds())
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[dnaby][{name}] 定时任务异常: {e}")


async def _run_hourly(name: str, coro_factory, mm: int, ss: int) -> None:
    """每小时 mm:ss 执行一次。"""
    while True:
        await asyncio.sleep((_next_hourly(mm, ss) - datetime.now(TZ)).total_seconds())
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[dnaby][{name}] 定时任务异常: {e}")


async def start_scheduled_tasks() -> list[asyncio.Task]:
    """创建并返回全部定时任务（由 main.py 保存引用并在 terminate 取消）。"""
    from .dna_ann import check_dna_ann_state
    from .dna_config.dna_config import DNAConfig, DNASignConfig
    from .dna_mh import dna_push_mh_notify
    from .dna_sign import clear_dna_sign_record, dna_auto_sign

    tasks: list[asyncio.Task] = []

    # 每日自动签到
    sign_h, sign_m = _parse_hhmm(DNASignConfig.get_config("SignTime").data, 0, 5)
    tasks.append(
        asyncio.create_task(
            _run_daily("auto_sign", dna_auto_sign, sign_h, sign_m),
            name="dnaby_auto_sign",
        )
    )

    # 每日 00:05 清理记录
    tasks.append(
        asyncio.create_task(
            _run_daily("clear_sign_record", clear_dna_sign_record, 0, 5),
            name="dnaby_clear_sign_record",
        )
    )

    # 每小时密函推送
    mh_mm, mh_ss = _parse_hhmm(DNAConfig.get_config("MHPushSubscribe").data, 0, 30)
    tasks.append(
        asyncio.create_task(
            _run_hourly("mh_push", dna_push_mh_notify, mh_mm, mh_ss),
            name="dnaby_mh_push",
        )
    )

    # 公告轮询
    ann_minutes = int(DNAConfig.get_config("AnnMinuteCheck").data or 10)
    tasks.append(
        asyncio.create_task(
            _run_loop("ann_check", check_dna_ann_state, max(1, ann_minutes) * 60),
            name="dnaby_ann_check",
        )
    )

    logger.info("[dnaby] 定时任务已启动。")
    return tasks
