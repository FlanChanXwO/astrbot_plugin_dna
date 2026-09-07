"""资源命令的 registry 归属、正则与 handler 边界测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.event import images_from_event
from src.entry.response import PlainTextResponse, ResponseFactory
from src.modules.operations import messages

OPERATIONS_SPEC_IDS = {
    "resource_status",
    "download_resource",
}


def test_operations_commands_are_registered_for_admin() -> None:
    specs = {spec.id: spec for spec in load_command_registry()}

    assert OPERATIONS_SPEC_IDS <= specs.keys()
    for command_id in OPERATIONS_SPEC_IDS:
        assert specs[command_id].permission == "admin", command_id
        assert specs[command_id].group == "资源管理"


def test_images_from_event_extracts_file_sources() -> None:
    from astrbot.api.message_components import Image

    class Event:
        def get_messages(self):
            return [
                Image.fromFileSystem("/tmp/a.png"),
                Image.fromBase64("aGVsbG8="),
            ]

    sources = images_from_event(Event())
    assert len(sources) == 2
    assert sources[0].endswith("a.png")
    assert sources[1].startswith("base64://")


@pytest.mark.asyncio
async def test_operations_handler_reports_service_missing() -> None:
    """缺少资源服务时 use case 必须返回显式不可用文案。"""

    spec = load_command_registry().get("resource_status")

    result = await cast(
        Awaitable,
        spec.use_case(
            SimpleNamespace(
                command_id="resource_status",
                text="kk资源状态",
                parameters={},
                actor=SimpleNamespace(
                    user_id="user-1", bot_id="bot-1", group_id="group-1"
                ),
                services={},
            ),
            load_command_registry(),
        ),
    )

    assert result == PlainTextResponse(messages.OPERATIONS_SERVICE_UNAVAILABLE)


@pytest.mark.asyncio
async def test_generated_resource_status_handler_yields_text() -> None:
    """真实生成 handler 把资源状态纯文本结果交给 AstrBot 边界。"""

    class FakeResourceService:
        async def status(self) -> PlainTextResponse:
            return PlainTextResponse("资源状态：\n资源仓库目录: /tmp/resources")

    class GeneratedOperationsPlugin:
        __module__ = "tests.generated_operations_plugin"

    class Event:
        def get_message_str(self) -> str:
            return "kk资源状态"

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def get_messages(self) -> list:
            return []

        def plain_result(self, text: str) -> str:
            return text

    spec = load_command_registry().get("resource_status")
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedOperationsPlugin, registry)
    plugin = GeneratedOperationsPlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"resource_update_service": FakeResourceService()},
        ),
    )

    handler = cast(Any, plugin).handle_resource_status
    result = [item async for item in handler(Event())]

    assert result == ["资源状态：\n资源仓库目录: /tmp/resources"]


@pytest.mark.asyncio
async def test_download_resource_yields_started_before_sync_result() -> None:
    """下载命令应先回执开始同步，再等待耗时同步结果。"""

    started = asyncio.Event()
    release = asyncio.Event()

    class FakeResourceService:
        async def sync_resources(self, _request: object) -> PlainTextResponse:
            started.set()
            await release.wait()
            return PlainTextResponse("资源已更新完成，版本 2.0")

    spec = load_command_registry().get("download_resource")
    request = SimpleNamespace(
        command_id="download_resource",
        text="kk同步资源",
        parameters={},
        actor=SimpleNamespace(user_id="user-1", bot_id="bot-1", group_id="group-1"),
        services={"resource_update_service": FakeResourceService()},
    )
    generator = cast(Any, spec.use_case(request, load_command_registry()))

    first = await anext(generator)
    assert first == PlainTextResponse("开始同步公共资源，请稍候，完成后会发送结果")
    assert not started.is_set()

    second_task = asyncio.create_task(anext(generator))
    await started.wait()
    assert not second_task.done()

    release.set()
    second = await second_task
    assert second == PlainTextResponse("资源已更新完成，版本 2.0")
