"""公共资源更新 use case。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from astrbot.api import logger

from ...entry.response import PlainTextResponse
from ...infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSyncResult,
)
from . import messages

SynchronizeFn = Callable[[], ResourceSyncResult]
_TaskValue = TypeVar("_TaskValue")


async def _drain_task(
    task: asyncio.Task[_TaskValue],
) -> tuple[_TaskValue | None, Exception | None, asyncio.CancelledError | None]:
    """在保留取消语义的同时等待任务结束，不用固定超时截断同步线程。"""

    interruption: asyncio.CancelledError | None = None
    while not task.done():
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if task.done():
                break
            if interruption is None:
                interruption = error
        except Exception as error:  # noqa: BLE001 - 排空边界必须观察注入任务的任意失败。
            return None, error, interruption
        else:
            return result, None, interruption

    if task.cancelled():
        return None, None, interruption
    try:
        return task.result(), None, interruption
    except asyncio.CancelledError:
        return None, None, interruption
    except Exception as error:  # noqa: BLE001 - 读取任务结果以避免未观察异常。
        return None, error, interruption


class ResourceUpdateService:
    """公共资源同步。

    同步只调用参数列表形式的 ``git``（浅克隆 / ``fetch`` / 候选校验 / fast-forward），
    Git 缺失、认证失败、远端失败、候选无效、非快进和本地修改均通过异常显露为可见文案，
    不自动覆盖本地修改。
    """

    def __init__(
        self,
        *,
        synchronize: SynchronizeFn,
    ) -> None:
        self.synchronize = synchronize
        self._flight_lock = asyncio.Lock()
        self._inflight: asyncio.Task[ResourceSyncResult] | None = None
        self._preheat_task: asyncio.Task[None] | None = None
        self._preheat_error: Exception | None = None

    @property
    def preheat_error(self) -> Exception | None:
        """返回最近一次后台预热的真实异常，供状态页和测试观察。"""

        return self._preheat_error

    async def synchronize_once(self) -> ResourceSyncResult:
        """取得共享同步任务；取消单个等待者不会取消底层同步。"""

        async with self._flight_lock:
            task = self._inflight
            if task is None or task.done():
                task = asyncio.create_task(asyncio.to_thread(self.synchronize))
                # 等待者全部取消后仍需消费线程任务的异常，避免 asyncio 只报未观察异常。
                task.add_done_callback(self._observe_sync_task)
                self._inflight = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._flight_lock:
                    if self._inflight is task:
                        self._inflight = None

    @staticmethod
    def _observe_sync_task(task: asyncio.Task[ResourceSyncResult]) -> None:
        """观察取消等待者后仍在运行的同步任务，并保留真实失败日志。"""

        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.warning(f"[dnaby][resources] 共享资源同步任务失败: {error}")

    async def start_preheat(self) -> None:
        """启动非阻塞资源预热；已有预热或同步任务时不重复发起。"""

        async with self._flight_lock:
            if self._preheat_task is not None and not self._preheat_task.done():
                return
            self._preheat_error = None
            self._preheat_task = asyncio.create_task(self._run_preheat())

    async def _run_preheat(self) -> None:
        try:
            await self.synchronize_once()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - 预热失败需记录真实异常。
            self._preheat_error = error
            logger.warning(f"[dnaby][resources] 后台预热失败: {error}")

    async def stop(self) -> None:
        """取消预热并排空共享同步，确保线程不会在 runtime 销毁后继续写资源。"""

        async with self._flight_lock:
            preheat_task = self._preheat_task
        if preheat_task is not None and not preheat_task.done():
            preheat_task.cancel()

        interruption: asyncio.CancelledError | None = None
        if preheat_task is not None:
            _, preheat_error, preheat_interruption = await _drain_task(preheat_task)
            interruption = preheat_interruption
            if preheat_error is not None:
                self._preheat_error = preheat_error
                logger.warning(f"[dnaby][resources] 后台预热失败: {preheat_error}")

        async with self._flight_lock:
            inflight = self._inflight
        if inflight is not None:
            _, sync_error, sync_interruption = await _drain_task(inflight)
            if interruption is None:
                interruption = sync_interruption
            if sync_error is not None:
                self._preheat_error = sync_error
                logger.warning(f"[dnaby][resources] 资源同步结束但失败: {sync_error}")

        async with self._flight_lock:
            if self._preheat_task is preheat_task:
                self._preheat_task = None
            if self._inflight is inflight:
                self._inflight = None
        if interruption is not None:
            raise interruption

    async def download_all(self, _request: object):
        """下载全部公共资源（浅克隆或 ff-only 更新）。"""

        try:
            result = await self.synchronize_once()
        except ResourceLocalChangesError as error:
            return PlainTextResponse(messages.RESOURCE_LOCAL_CHANGES.format(detail=str(error)))
        except ResourceRemoteMismatchError:
            return PlainTextResponse(messages.RESOURCE_REMOTE_MISMATCH)
        except GitUnavailableError:
            return PlainTextResponse(messages.RESOURCE_GIT_UNAVAILABLE)
        except ResourceSyncError as error:
            return PlainTextResponse(messages.RESOURCE_SYNC_FAILED.format(detail=str(error)))
        action = "已克隆" if result.action == "cloned" else "已更新"
        return PlainTextResponse(messages.RESOURCE_DOWNLOADED.format(action=action, version=result.resource_version))

__all__ = ["ResourceUpdateService"]
