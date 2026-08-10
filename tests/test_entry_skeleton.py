"""v0.1 入口骨架的 AstrBot 集成契约测试。"""

import pytest
from astrbot.api.star import Star

from main import DnabyPlugin
from src.entry.lifecycle import PluginLifecycle
from src.entry.web import WebRegistrar, WebRoute


class FakeContext:
    """只实现入口骨架本轮需要观察的 Context 行为。"""

    def __init__(self) -> None:
        self.web_apis: list[tuple[str, object, list[str], str]] = []

    def register_web_api(
        self,
        route: str,
        handler: object,
        methods: list[str],
        description: str,
    ) -> None:
        self.web_apis.append((route, handler, methods, description))


@pytest.mark.asyncio
async def test_empty_plugin_can_initialize_and_terminate_without_registrations():
    """空能力 v0.1 入口可被 AstrBot 加载和卸载，且不注册尚未实现的入口。"""

    context = FakeContext()
    plugin = DnabyPlugin(context, {})

    assert isinstance(plugin, Star)

    await plugin.initialize()
    await plugin.terminate()

    assert context.web_apis == []


@pytest.mark.asyncio
async def test_plugin_lifecycle_preserves_hook_order_and_is_idempotent():
    """扩展点按声明/逆序运行，重复生命周期调用不重复执行。"""

    calls: list[str] = []

    async def start_one() -> None:
        calls.append("start-one")

    async def start_two() -> None:
        calls.append("start-two")

    async def stop_one() -> None:
        calls.append("stop-one")

    async def stop_two() -> None:
        calls.append("stop-two")

    lifecycle = PluginLifecycle(
        start_hooks=(start_one, start_two),
        stop_hooks=(stop_one, stop_two),
    )

    await lifecycle.initialize()
    await lifecycle.initialize()
    await lifecycle.terminate()
    await lifecycle.terminate()

    assert calls == ["start-one", "start-two", "stop-two", "stop-one"]


@pytest.mark.asyncio
async def test_web_registrar_maps_routes_to_astrbot_once():
    """Web route 描述被转换为 AstrBot 参数，并且重复初始化不重复注册。"""

    context = FakeContext()

    async def handler(_request: object) -> None:
        return None

    registrar = WebRegistrar(
        context,
        (WebRoute("/test", handler, ("GET", "POST"), "测试路由"),),
    )

    await registrar.initialize()
    await registrar.initialize()

    assert context.web_apis == [("/test", handler, ["GET", "POST"], "测试路由")]
