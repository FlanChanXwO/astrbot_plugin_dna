"""插件生命周期边界。

生命周期只负责按注册顺序启动、按逆序停止扩展点，不在这里承载业务初始化。
这样可以让 AstrBot 的 ``initialize()/terminate()`` 与业务模块解耦，并在测试中
直接观察启动和停止顺序。
"""

from __future__ import annotations

from builtins import BaseExceptionGroup, ExceptionGroup
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

    @property
    def started(self) -> bool:
        """返回当前生命周期是否已经完成启动。"""

        return self._started

    async def initialize(self) -> None:
        """按声明顺序启动扩展点；重复初始化不重复注册资源。"""

        if self._started:
            return

        try:
            for hook in self._start_hooks:
                await hook()
        except BaseException as start_error:
            # 临时标记为已启动，复用 terminate 的逆序清理路径；terminate 会在
            # 清理完成后复位，确保 AstrBot 不调用 terminate 时也不会遗留任务。
            self._started = True
            try:
                await self.terminate()
            except BaseException as cleanup_error:  # noqa: BLE001
                raise BaseExceptionGroup(
                    "插件初始化失败且清理失败",
                    [start_error, cleanup_error],
                ) from start_error
            raise
        self._started = True

    async def terminate(self) -> None:
        """按逆序停止扩展点；停止异常向上暴露，便于 AstrBot 记录。"""

        if not self._started:
            return

        errors: list[Exception] = []
        try:
            for hook in reversed(self._stop_hooks):
                try:
                    await hook()
                except Exception as error:  # noqa: BLE001
                    errors.append(error)
        finally:
            self._started = False

        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise ExceptionGroup("多个插件清理 hook 失败", errors)
