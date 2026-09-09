"""插件生命周期边界。

生命周期只负责按注册顺序启动、按逆序停止扩展点，不在这里承载业务初始化。
这样可以让 AstrBot 的 ``initialize()/terminate()`` 与业务模块解耦，并在测试中
直接观察启动和停止顺序。
"""

from __future__ import annotations

import asyncio
from builtins import BaseExceptionGroup
from collections.abc import Awaitable, Callable, Iterable, Mapping
from time import perf_counter

from astrbot.api import logger

LifecycleHook = Callable[[], Awaitable[None]]


def _hook_label(hook: LifecycleHook, index: int) -> str:
    """返回用于 timing 日志的稳定 hook 名称，不读取 hook 的运行时数据。"""

    label = getattr(hook, "__qualname__", None) or getattr(hook, "__name__", None)
    if isinstance(label, str) and label:
        return label
    return f"hook_{index}"


class PluginLifecycle:
    """管理插件扩展点的启动和停止，不吞掉扩展点异常。"""

    def __init__(
        self,
        *,
        start_hooks: Iterable[LifecycleHook] = (),
        stop_hooks: Iterable[LifecycleHook] = (),
        finalizer_hooks: Iterable[LifecycleHook] = (),
    ) -> None:
        self._start_hooks = tuple(start_hooks)
        self._stop_hooks = tuple(stop_hooks)
        self._finalizer_hooks = tuple(finalizer_hooks)
        self._started = False
        self._fully_started = False
        self._completed_start_count = 0
        self._last_timings: dict[str, float] = {}
        # 生命周期转换必须串行，否则并发重载会重复注册或重复释放同一资源。
        self._lifecycle_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        """返回当前生命周期是否已经完成启动。"""

        return self._started and self._fully_started

    @property
    def last_timings(self) -> Mapping[str, float]:
        """返回最近一次生命周期操作的总耗时和阶段耗时（单位：秒）。"""

        return dict(self._last_timings)

    def _publish_timings(
        self,
        operation: str,
        started_at: float,
        timings: dict[str, float],
        labels: dict[str, str],
    ) -> None:
        total = perf_counter() - started_at
        timings[f"{operation}.total"] = total
        self._last_timings = dict(timings)
        logger.debug(
            "[dnaby][lifecycle] operation=%s total_seconds=%.6f phase_seconds=%s",
            operation,
            total,
            {
                key: {"seconds": round(value, 6), "hook": labels.get(key, "")}
                for key, value in timings.items()
                if key != f"{operation}.total"
            },
        )

    async def initialize(self) -> None:
        """按声明顺序启动扩展点；重复初始化不重复注册资源。"""

        async with self._lifecycle_lock:
            if self._started:
                return

            started_at = perf_counter()
            timings: dict[str, float] = {}
            labels: dict[str, str] = {}
            completed_start_count = 0
            started_start_count = 0
            self._fully_started = False
            self._completed_start_count = 0
            try:
                for index, hook in enumerate(self._start_hooks):
                    phase_started_at = perf_counter()
                    phase_key = f"initialize.phase_{index}"
                    labels[phase_key] = _hook_label(hook, index)
                    # 先记录已进入的阶段，失败阶段可能已创建部分资源，需要纳入回滚。
                    started_start_count = index + 1
                    try:
                        await hook()
                    finally:
                        timings[phase_key] = perf_counter() - phase_started_at
                    completed_start_count += 1
                self._completed_start_count = completed_start_count
                self._fully_started = True
                self._started = True
            except BaseException as start_error:
                # 失败阶段可能已创建资源；清理计数包含当前正在执行的阶段。
                self._completed_start_count = started_start_count
                # 临时标记为已启动，复用 terminate 的逆序清理路径；清理完成后
                # 会复位状态，确保 AstrBot 不调用 terminate 时也不会遗留任务。
                self._started = True
                try:
                    await self._terminate_locked(operation="initialize.cleanup")
                except BaseException as cleanup_error:  # noqa: BLE001
                    raise BaseExceptionGroup(
                        "插件初始化失败且清理失败",
                        [start_error, cleanup_error],
                    ) from start_error
                raise
            finally:
                self._publish_timings("initialize", started_at, timings, labels)

    async def terminate(self) -> None:
        """按逆序停止扩展点；停止异常向上暴露，便于 AstrBot 记录。"""

        async with self._lifecycle_lock:
            await self._terminate_locked(operation="terminate")

    async def _terminate_locked(self, *, operation: str) -> None:
        """在已持有生命周期锁时完成清理。"""

        if not self._started:
            return

        started_at = perf_counter()
        timings: dict[str, float] = {}
        labels: dict[str, str] = {}
        errors: list[BaseException] = []
        if self._fully_started:
            stop_hooks = self._stop_hooks
        else:
            # stop_hooks 与 start_hooks 按阶段对齐；计数包含失败阶段，
            # 因此释放所有已进入阶段的前缀，避免遗漏部分创建的资源。
            stop_hooks = self._stop_hooks[: self._completed_start_count]

        try:
            for index in range(len(stop_hooks) - 1, -1, -1):
                hook = stop_hooks[index]
                phase_started_at = perf_counter()
                phase_key = f"{operation}.phase_{index}"
                labels[phase_key] = _hook_label(hook, index)
                try:
                    await hook()
                except BaseException as error:  # noqa: BLE001
                    # CancelledError 也不能中断剩余清理；循环结束后再把取消
                    # 语义传回调用方，避免资源只清理了一半。
                    errors.append(error)
                finally:
                    timings[phase_key] = perf_counter() - phase_started_at

            # finalizer 不属于可启动步骤，始终在业务步骤之后运行；因此即使
            # 初始化部分失败，也会释放构造阶段已经持有的 transport/DB 资源。
            for index, hook in enumerate(self._finalizer_hooks):
                phase_started_at = perf_counter()
                phase_key = f"{operation}.finalizer_{index}"
                labels[phase_key] = _hook_label(hook, index)
                try:
                    await hook()
                except BaseException as error:  # noqa: BLE001
                    errors.append(error)
                finally:
                    timings[phase_key] = perf_counter() - phase_started_at
        finally:
            self._started = False
            self._fully_started = False
            self._completed_start_count = 0
            self._publish_timings(operation, started_at, timings, labels)

        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise BaseExceptionGroup("多个插件清理 hook 失败", errors)
