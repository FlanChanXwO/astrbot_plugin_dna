"""插件生命周期边界。

生命周期只负责按注册顺序启动、按逆序停止扩展点，不在这里承载业务初始化。
这样可以让 AstrBot 的 ``initialize()/terminate()`` 与业务模块解耦，并在测试中
直接观察启动和停止顺序。
"""

from __future__ import annotations

import asyncio
from builtins import BaseExceptionGroup
from collections.abc import Awaitable, Callable, Iterable

LifecycleHook = Callable[[], Awaitable[None]]


class PluginLifecycle:
    """管理插件扩展点的启动和停止，不吞掉扩展点异常。"""

    def __init__(
        self,
        *,
        start_hooks: Iterable[LifecycleHook] = (),
        stop_hooks: Iterable[LifecycleHook] = (),
    ) -> None:
        self._start_hooks = tuple(start_hooks)
        self._stop_hooks = tuple(stop_hooks)
        self._started = False
        # 生命周期转换必须串行，否则并发重载会重复注册或重复释放同一资源。
        self._lifecycle_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        """返回当前生命周期是否已经完成启动。"""

        return self._started

    async def initialize(self) -> None:
        """按声明顺序启动扩展点；重复初始化不重复注册资源。"""

        async with self._lifecycle_lock:
            if self._started:
                return

            try:
                for hook in self._start_hooks:
                    await hook()
            except BaseException as start_error:
                # 临时标记为已启动，复用 terminate 的逆序清理路径；清理完成后
                # 会复位状态，确保 AstrBot 不调用 terminate 时也不会遗留任务。
                self._started = True
                try:
                    await self._terminate_locked()
                except BaseException as cleanup_error:  # noqa: BLE001
                    raise BaseExceptionGroup(
                        "插件初始化失败且清理失败",
                        [start_error, cleanup_error],
                    ) from start_error
                raise
            self._started = True

    async def terminate(self) -> None:
        """按逆序停止扩展点；停止异常向上暴露，便于 AstrBot 记录。"""

        async with self._lifecycle_lock:
            await self._terminate_locked()

    async def _terminate_locked(self) -> None:
        """在已持有生命周期锁时完成清理。"""

        if not self._started:
            return

        errors: list[BaseException] = []
        try:
            for hook in reversed(self._stop_hooks):
                try:
                    await hook()
                except BaseException as error:  # noqa: BLE001
                    # CancelledError 也不能中断剩余清理；循环结束后再把取消
                    # 语义传回调用方，避免资源只清理了一半。
                    errors.append(error)
        finally:
            self._started = False

        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise BaseExceptionGroup("多个插件清理 hook 失败", errors)
