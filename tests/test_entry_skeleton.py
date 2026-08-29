"""v0.1 入口骨架的 AstrBot 集成契约测试。"""

import asyncio
from builtins import ExceptionGroup
from pathlib import Path

import pytest
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Star

from main import DnabyPlugin
from src.entry.lifecycle import PluginLifecycle
from src.entry.response import (
    ChainResponse,
    ImageResponse,
    PlainTextResponse,
    ResponseFactory,
)
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
async def test_plugin_can_initialize_and_terminate_with_admin_web_registrations():
    """入口可被 AstrBot 加载和卸载，并注册唯一的 Dashboard 管理路由。"""

    context = FakeContext()
    plugin = DnabyPlugin(context)

    assert isinstance(plugin, Star)

    await plugin.initialize()
    await plugin.terminate()

    assert context.web_apis
    assert "/astrbot_plugin_dnaby/admin/bootstrap" in {
        route[0] for route in context.web_apis
    }
    assert len({(route[0], tuple(route[2])) for route in context.web_apis}) == len(
        context.web_apis
    )


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
async def test_plugin_lifecycle_serializes_concurrent_initialization():
    """并发初始化只允许一次完整启动，后续调用共享同一完成结果。"""

    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def start() -> None:
        calls.append("start")
        entered.set()
        await release.wait()

    lifecycle = PluginLifecycle(start_hooks=(start,))
    first = asyncio.create_task(lifecycle.initialize())
    await entered.wait()
    second = asyncio.create_task(lifecycle.initialize())
    await asyncio.sleep(0)
    release.set()

    await asyncio.gather(first, second)

    assert calls == ["start"]
    assert lifecycle.started is True


@pytest.mark.asyncio
async def test_plugin_lifecycle_serializes_concurrent_termination():
    """并发终止只允许一次逆序清理。"""

    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def stop() -> None:
        calls.append("stop")
        entered.set()
        await release.wait()

    lifecycle = PluginLifecycle(stop_hooks=(stop,))
    await lifecycle.initialize()
    first = asyncio.create_task(lifecycle.terminate())
    await entered.wait()
    second = asyncio.create_task(lifecycle.terminate())
    await asyncio.sleep(0)
    release.set()

    await asyncio.gather(first, second)

    assert calls == ["stop"]
    assert lifecycle.started is False


@pytest.mark.asyncio
async def test_plugin_lifecycle_finishes_cleanup_after_cancellation():
    """终止任务被取消后仍执行剩余清理，并继续暴露取消语义。"""

    calls: list[str] = []
    entered = asyncio.Event()

    async def stop_first() -> None:
        calls.append("stop-first")

    async def stop_second() -> None:
        calls.append("stop-second")
        entered.set()
        await asyncio.Event().wait()

    lifecycle = PluginLifecycle(stop_hooks=(stop_first, stop_second))
    await lifecycle.initialize()
    termination = asyncio.create_task(lifecycle.terminate())
    await entered.wait()
    termination.cancel()

    with pytest.raises(asyncio.CancelledError):
        await termination

    assert calls == ["stop-second", "stop-first"]
    assert lifecycle.started is False


@pytest.mark.asyncio
async def test_plugin_lifecycle_cleans_up_when_start_hook_fails():
    """启动中途失败时，已组装的扩展点仍需按逆序清理。"""

    calls: list[str] = []

    async def start_one() -> None:
        calls.append("start-one")

    async def start_two() -> None:
        calls.append("start-two")
        raise RuntimeError("start-two failed")

    async def stop_one() -> None:
        calls.append("stop-one")

    async def stop_two() -> None:
        calls.append("stop-two")

    lifecycle = PluginLifecycle(
        start_hooks=(start_one, start_two),
        stop_hooks=(stop_one, stop_two),
    )

    with pytest.raises(RuntimeError, match="start-two failed"):
        await lifecycle.initialize()

    assert calls == ["start-one", "start-two", "stop-two", "stop-one"]
    assert lifecycle.started is False


@pytest.mark.asyncio
async def test_plugin_lifecycle_reports_cleanup_errors_after_start_failure():
    """清理 hook 失败时仍继续清理，并同时暴露启动与清理异常。"""

    calls: list[str] = []

    async def start_one() -> None:
        calls.append("start-one")

    async def start_two() -> None:
        calls.append("start-two")
        raise RuntimeError("start-two failed")

    async def stop_one() -> None:
        calls.append("stop-one")

    async def stop_two() -> None:
        calls.append("stop-two")
        raise ValueError("stop-two failed")

    lifecycle = PluginLifecycle(
        start_hooks=(start_one, start_two),
        stop_hooks=(stop_one, stop_two),
    )

    with pytest.raises(ExceptionGroup) as error_info:
        await lifecycle.initialize()

    assert calls == ["start-one", "start-two", "stop-two", "stop-one"]
    assert lifecycle.started is False
    assert {str(error) for error in error_info.value.exceptions} == {
        "start-two failed",
        "stop-two failed",
    }


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


def test_response_factory_converts_framework_free_dtos():
    """text/chain/image DTO 都只在 response 边界触碰 AstrBot event。"""

    class Event:
        def plain_result(self, text: str) -> tuple[str, object]:
            return ("plain", text)

        def chain_result(self, components: object) -> tuple[str, object]:
            return ("chain", components)

        def image_result(self, image: object) -> tuple[str, object]:
            return ("image", image)

    event = Event()
    factory = ResponseFactory()

    assert factory.build(event, PlainTextResponse("文本")) == ("plain", "文本")
    assert factory.build(event, ChainResponse(["链"])) == ("chain", ["链"])
    assert factory.build(event, ImageResponse(b"image")) == ("image", b"image")


def test_response_factory_tracks_only_generated_images_for_event_cleanup(
    tmp_path: Path,
):
    """合成图片交给 AstrBot 事件清理，原始资源不能被一并删除。"""

    class Event(AstrMessageEvent):
        def __init__(self) -> None:
            self._temporary_local_files: list[str] = []

        def image_result(self, image: object) -> tuple[str, object]:
            return ("image", image)

        def chain_result(self, components: object) -> tuple[str, object]:
            return ("chain", components)

    rendered_dir = tmp_path / "rendered"
    generated = rendered_dir / "rendered.png"
    original = tmp_path / "resources" / "original-panel.png"
    rendered_dir.mkdir()
    original.parent.mkdir()
    generated.write_bytes(b"generated")
    original.write_bytes(b"original")
    event = Event()

    ResponseFactory(temporary_roots=(rendered_dir,)).build(
        event,
        ChainResponse(
            (
                ImageResponse(str(generated), temporary=True),
                ImageResponse(str(original)),
            ),
        ),
    )
    event.cleanup_temporary_local_files()

    assert not generated.exists()
    assert original.exists()


def test_response_factory_rejects_temporary_image_outside_rendered_root(tmp_path: Path):
    """临时标记不能使事件清理器删除运行期渲染目录之外的文件。"""

    class Event:
        def track_temporary_local_file(self, _path: str) -> None:
            raise AssertionError("越界路径不能登记到事件清理器")

    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    original = tmp_path / "resources" / "original-panel.png"
    original.parent.mkdir()
    original.write_bytes(b"original")

    with pytest.raises(ValueError, match="受控渲染目录"):
        ResponseFactory(temporary_roots=(rendered_dir,)).build(
            Event(),
            ImageResponse(str(original), temporary=True),
        )

    assert original.exists()


def test_response_factory_plain_with_need_at_in_group_creates_at_chain():
    """群聊中 need_at=True 的纯文本响应转换为 At + Plain 消息链。"""
    from astrbot.api.message_components import At, Plain

    class GroupEvent:
        def get_group_id(self) -> str:
            return "group-1"

        def get_sender_id(self) -> str:
            return "user-123"

        def chain_result(self, components: object) -> tuple[str, object]:
            return ("chain", components)

        def plain_result(self, text: str) -> tuple[str, object]:
            return ("plain", text)

    class DirectEvent:
        def get_group_id(self) -> None:
            return None

        def get_sender_id(self) -> str:
            return "user-123"

        def chain_result(self, components: object) -> tuple[str, object]:
            return ("chain", components)

        def plain_result(self, text: str) -> tuple[str, object]:
            return ("plain", text)

    factory = ResponseFactory()
    group_res = factory.build(GroupEvent(), PlainTextResponse("测试消息", need_at=True))
    assert group_res[0] == "chain"
    components = group_res[1]
    assert len(components) == 2
    assert isinstance(components[0], At)
    assert components[0].qq == "user-123"
    assert isinstance(components[1], Plain)
    assert components[1].text == "测试消息"

    direct_res = factory.build(
        DirectEvent(), PlainTextResponse("测试消息", need_at=True)
    )
    assert direct_res == ("plain", "测试消息")

    no_at_res = factory.build(
        GroupEvent(), PlainTextResponse("测试消息", need_at=False)
    )
    assert no_at_res == ("plain", "测试消息")


def test_build_runtime_handles_existing_resource_dir_without_manifest(tmp_path: Path):
    """当 resources 目录存在但尚未拉取 manifest 时，runtime 组装不抛出异常。"""
    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    db = AsyncDatabase.from_data_dir(tmp_path)
    (tmp_path / "resources").mkdir(parents=True, exist_ok=True)
    runtime = build_runtime(FakeContext(), {}, database=db)
    assert runtime is not None
