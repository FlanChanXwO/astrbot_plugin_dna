"""本地登录页服务。

AstrBot 的 ``register_web_api`` 由 Dashboard 统一鉴权，不能直接作为普通用户
打开的登录页。这里仅承载登录路由，并复用现有 handler，避免为 local 模式引入
第二套登录业务逻辑。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any

from aiohttp import web
from astrbot.api.web import PluginRequest, bind_request_context
from starlette.responses import Response

Route = tuple[str, Callable[..., Any], list[str], str]


class _MultiItems:
    """给 ``PluginRequest`` 提供 AstrBot 需要的多值参数接口。"""

    def __init__(self, pairs: Iterable[tuple[str, Any]]) -> None:
        self._pairs = list(pairs)

    def multi_items(self) -> list[tuple[str, Any]]:
        return self._pairs


class _AioHttpRequest:
    """将 aiohttp 请求转换为 ``PluginRequest`` 可消费的最小接口。"""

    def __init__(self, request: web.Request) -> None:
        self._request = request
        self.method = request.method
        self.url = SimpleNamespace(path=request.path)
        self.headers = request.headers
        self.cookies = request.cookies
        self.client = SimpleNamespace(host=request.remote)
        self.query_params = _MultiItems(_query_pairs(request.query))

    async def body(self) -> bytes:
        return await self._request.read()

    async def json(self) -> Any:
        return await self._request.json()

    async def form(self) -> _MultiItems:
        return _MultiItems(_query_pairs(await self._request.post()))


def _query_pairs(values: Any) -> list[tuple[str, Any]]:
    """保留重复参数，兼容 aiohttp 不同版本的 MultiDict 接口。"""
    try:
        return list(values.items(getall=True))
    except TypeError:
        return list(values.items())


def _to_aiohttp_response(result: Any) -> web.StreamResponse:
    if isinstance(result, Response):
        headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower() != "content-length"
        }
        return web.Response(
            body=result.body,
            status=result.status_code,
            headers=headers,
        )
    if isinstance(result, (dict, list)):
        return web.json_response(result)
    if result is None:
        return web.Response(status=204)
    if isinstance(result, bytes):
        return web.Response(body=result)
    if isinstance(result, str):
        return web.Response(text=result)
    raise TypeError(f"不支持的登录路由响应类型: {type(result)!r}")


class LocalLoginServer:
    """随插件生命周期启动的本地登录 HTTP 服务。"""

    def __init__(
        self,
        routes: Iterable[Route],
        *,
        host: str,
        port: int,
        public_host: str | None = None,
        base_path: str = "/astrbot_plugin_dnaby",
    ) -> None:
        if not host.strip():
            raise ValueError("本地登录服务 host 不能为空")
        if not 0 <= port <= 65535:
            raise ValueError(f"本地登录服务 port 无效: {port}")
        self.host = host.strip()
        self.port = port
        self.public_host = public_host or (
            "localhost" if self.host in {"0.0.0.0", "127.0.0.1", "::"} else self.host
        )
        self.base_path = base_path.rstrip("/")
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._actual_port: int | None = None

        for route, handler, methods, _description in routes:
            for method in methods:
                self._app.router.add_route(
                    method,
                    route,
                    self._make_route_handler(handler),
                )

    @property
    def base_url(self) -> str:
        if self._actual_port is None:
            raise RuntimeError("本地登录服务尚未启动")
        return f"http://{self.public_host}:{self._actual_port}{self.base_path}"

    async def start(self) -> None:
        if self._runner is not None:
            raise RuntimeError("本地登录服务已经启动")
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        await self._site.start()
        server = getattr(self._site, "_server", None)
        sockets = getattr(server, "sockets", ())
        if not sockets:
            await self.stop()
            raise RuntimeError("本地登录服务启动后未取得监听 socket")
        self._actual_port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._actual_port = None

    def _make_route_handler(self, handler: Callable[..., Any]) -> Callable[[web.Request], Any]:
        async def route_handler(request: web.Request) -> web.StreamResponse:
            adapter = _AioHttpRequest(request)
            plugin_request = PluginRequest(
                adapter,
                path_params=dict(request.match_info),
                plugin_name="astrbot_plugin_dnaby",
            )
            with bind_request_context(plugin_request):
                result = handler(**dict(request.match_info))
                if inspect.isawaitable(result):
                    result = await result
            return _to_aiohttp_response(result)

        return route_handler


__all__ = ["LocalLoginServer"]
