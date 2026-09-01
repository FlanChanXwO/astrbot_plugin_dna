"""短生命周期外部请求的全局并发门。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from functools import wraps
from typing import Any, TypeVar, cast

T = TypeVar("T")
Operation = Callable[[], Awaitable[T]]


def gated_transport_method(
    method: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """让 transport 公共短请求复用实例级并发门；无 gate 时保持兼容。"""

    @wraps(method)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> T:
        gate = getattr(self, "request_gate", None)
        if gate is None:
            return await method(self, *args, **kwargs)
        return await gate.run(lambda: method(self, *args, **kwargs))

    return wrapped


class RequestConcurrencyGate:
    """限制短请求并发，并为有 key 的请求提供进程内 single-flight。"""

    def __init__(self, max_concurrent_requests: int) -> None:
        if (
            not isinstance(max_concurrent_requests, int)
            or isinstance(max_concurrent_requests, bool)
            or max_concurrent_requests < 1
        ):
            raise ValueError("max_concurrent_requests 必须是大于等于 1 的整数")
        self.limit = max_concurrent_requests
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._registry_lock = asyncio.Lock()
        self._in_flight: dict[Hashable, asyncio.Task[Any]] = {}
        self._active = 0

    @property
    def active_count(self) -> int:
        """当前正在执行远程操作的数量。"""

        return self._active

    @property
    def in_flight_count(self) -> int:
        """当前 single-flight registry 中的任务数量。"""

        return len(self._in_flight)

    async def _run(self, operation: Operation[T]) -> T:
        async with self._semaphore:
            self._active += 1
            try:
                return await operation()
            finally:
                self._active -= 1

    async def run(
        self,
        operation: Operation[T],
        *,
        key: Hashable | None = None,
    ) -> T:
        """执行短请求；有 key 时让并发调用共享同一个底层任务。"""

        if not callable(operation):
            raise TypeError("operation 必须是可调用的异步函数")
        if key is None:
            return await self._run(operation)

        async with self._registry_lock:
            task = self._in_flight.get(key)
            if task is None:
                task = asyncio.create_task(self._run(operation))
                self._in_flight[key] = task
                task.add_done_callback(
                    lambda completed: asyncio.create_task(
                        self._remove_completed(key, completed)
                    )
                )
        return await asyncio.shield(cast(asyncio.Task[T], task))

    async def _remove_completed(
        self, key: Hashable, completed: asyncio.Task[Any]
    ) -> None:
        async with self._registry_lock:
            if self._in_flight.get(key) is completed:
                self._in_flight.pop(key, None)


__all__ = ["RequestConcurrencyGate", "gated_transport_method"]
