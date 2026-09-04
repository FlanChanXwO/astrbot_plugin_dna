"""Goal 6 CHECK-3：生命周期失败收尾与路由注册原子性契约。"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from aiohttp import web

from src.entry.web import WebRegistrar, WebRoute
from src.infrastructure.http.login_server import LocalLoginServer


@pytest.mark.asyncio
async def test_local_login_server_can_retry_after_listener_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """监听 socket 启动失败后必须清理 runner，后续重试不能被脏状态阻塞。"""

    original_start: Callable[..., object] = web.TCPSite.start
    attempts = 0

    async def fail_once(site: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("listener start failed")
        result = original_start(site)
        if hasattr(result, "__await__"):
            await result

    monkeypatch.setattr(web.TCPSite, "start", fail_once)
    server = LocalLoginServer((), host="127.0.0.1", port=0)

    with pytest.raises(OSError, match="listener start failed"):
        await server.start()

    await server.start()
    try:
        assert server.base_url.startswith("http://localhost:")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_web_registrar_rolls_back_partial_registration_on_failure() -> None:
    """路由注册中途失败时不能把半套插件路由遗留在 AstrBot registry。"""

    class Context:
        def __init__(self) -> None:
            self.registered_web_apis: list[tuple[object, ...]] = []
            self.fail_on_second = True

        def register_web_api(
            self,
            route: str,
            handler: object,
            methods: list[str],
            description: str,
        ) -> None:
            self.registered_web_apis.append((route, handler, methods, description))
            if self.fail_on_second and len(self.registered_web_apis) == 2:
                raise RuntimeError("route registration failed")

    async def handler(_request: object) -> None:
        return None

    context = Context()
    registrar = WebRegistrar(
        context,  # type: ignore[arg-type]
        (
            WebRoute("/astrbot_plugin_dnaby/one", handler, ("GET",), "one"),
            WebRoute("/astrbot_plugin_dnaby/two", handler, ("GET",), "two"),
        ),
    )

    with pytest.raises(RuntimeError, match="route registration failed"):
        await registrar.initialize()

    assert context.registered_web_apis == []
    assert registrar.registered is False

    context.fail_on_second = False
    await registrar.initialize()
    assert len(context.registered_web_apis) == 2
    await registrar.stop()
    assert context.registered_web_apis == []
