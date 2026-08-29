"""AstrBot Web API 注册边界。

业务模块只提供 ``WebRoute``，由这一层把路由描述转换成
``Context.register_web_api`` 调用。管理页路由由 bootstrap 注入；本层不实现业务逻辑，
也不建立独立的未认证 HTTP 入口。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from astrbot.api.star import Context

WebHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class WebRoute:
    """一个可交给 AstrBot 注册的 Web API 路由。"""

    path: str
    handler: WebHandler
    methods: tuple[str, ...]
    description: str


class WebRegistrar:
    """把路由描述注册到 AstrBot，并保证同一 runtime 只注册一次。"""

    def __init__(
        self,
        context: Context,
        routes: Iterable[WebRoute] = (),
    ) -> None:
        self._context = context
        self._routes = tuple(routes)
        self._registered = False

    @property
    def registered(self) -> bool:
        """返回本 registrar 是否已经完成注册。"""

        return self._registered

    async def initialize(self) -> None:
        """将路由交给 AstrBot；注册失败时保留异常并不伪造成功。"""

        if self._registered:
            return

        for route in self._routes:
            self._context.register_web_api(
                route.path,
                route.handler,
                list(route.methods),
                route.description,
            )
        self._registered = True
