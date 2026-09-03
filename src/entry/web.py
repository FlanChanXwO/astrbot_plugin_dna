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

    @staticmethod
    def _registry(context: Context) -> list[tuple[Any, ...]] | None:
        registered_web_apis = getattr(context, "registered_web_apis", None)
        if registered_web_apis is None and not isinstance(context, Context):
            # 单元测试允许只实现公开 register_web_api()；真实 AstrBot Context 若移除
            # registry，则必须显式失败，避免卸载逻辑静默失效。
            return None
        if not isinstance(registered_web_apis, list):
            raise TypeError("AstrBot Context.registered_web_apis 必须是 list")
        return registered_web_apis

    @classmethod
    def unregister_plugin_routes(cls, context: Context, plugin_name: str) -> None:
        """从 AstrBot 全局 Web registry 移除指定插件命名空间下的全部路由。"""

        registered_web_apis = cls._registry(context)
        if registered_web_apis is None:
            return
        prefix = f"/{plugin_name}/"
        registered_web_apis[:] = [
            registration
            for registration in registered_web_apis
            if not (
                isinstance(registration, tuple)
                and registration
                and isinstance(registration[0], str)
                and registration[0].startswith(prefix)
            )
        ]

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
