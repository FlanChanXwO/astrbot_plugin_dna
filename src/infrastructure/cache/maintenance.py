"""统一缓存和 rendered 文件的运行期维护任务。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from astrbot.api import logger

from ..rendering.temporary import RenderedFileStore
from .manager import CacheManager


@dataclass(frozen=True, slots=True)
class CacheCleanupReport:
    """一次缓存维护的汇总结果。"""

    cache_removed: int
    rendered_removed: int
    rendered_skipped_active: int
    rendered_skipped_invalid: int


class CacheMaintenance:
    """按内容 TTL 扫描周期触发统一缓存清理，并提供显式的一次性入口。"""

    def __init__(
        self,
        manager: CacheManager,
        rendered: RenderedFileStore,
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("缓存维护周期必须大于零")
        self.manager = manager
        self.rendered = rendered
        self.interval_seconds = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        """返回后台清理循环是否存在。"""

        return self._task is not None and not self._task.done()

    async def cleanup_once(self, *, now: datetime | None = None) -> CacheCleanupReport:
        """执行一次持久缓存和 rendered 文件清理。"""

        cache_removed = await self.manager.cleanup(now=now)
        rendered_report = self.rendered.cleanup(now=now)
        return CacheCleanupReport(
            cache_removed=cache_removed,
            rendered_removed=rendered_report.removed,
            rendered_skipped_active=rendered_report.skipped_active,
            rendered_skipped_invalid=rendered_report.skipped_invalid,
        )

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.cleanup_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - 后台清理必须记录真实失败并继续循环。
                logger.warning(
                    "[dnaby][cache] 缓存清理任务失败: %s",
                    type(error).__name__,
                )

    async def start(self) -> None:
        """启动一次启动期清理和幂等后台循环。"""

        async with self._lifecycle_lock:
            if self.started:
                return
            await self.cleanup_once()
            self._task = asyncio.create_task(
                self._run(),
                name="dnaby_cache_cleanup",
            )

    async def stop(self) -> None:
        """取消后台清理循环并等待其退出。"""

        async with self._lifecycle_lock:
            task = self._task
            self._task = None
            if task is None:
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


__all__ = ["CacheCleanupReport", "CacheMaintenance"]
