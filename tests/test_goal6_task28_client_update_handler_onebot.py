"""Goal 6 T28：真实客户端更新 handler 与 OneBot 合并转发组合证据。"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from astrbot.api.message_components import Nodes as AstrNodes

from src.entry.commands import (
    CommandRegistry,
    install_command_handlers,
    load_command_registry,
)
from src.entry.response import ResponseFactory
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateObservation,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)


class _HandlerEvent:
    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name
        self.unified_msg_origin = f"{platform_name}:group:group-1"

    def get_platform_name(self) -> str:
        return self.platform_name

    def get_message_str(self) -> str:
        return "kk客户端更新"

    def get_sender_id(self) -> str:
        return "user-1"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_group_id(self) -> str:
        return "group-1"

    def get_messages(self) -> list[object]:
        return []

    def plain_result(self, text: str) -> tuple[str, str]:
        return ("plain", text)

    def chain_result(self, components: object) -> tuple[str, object]:
        return ("chain", components)


class _ChannelTransport:
    def __init__(self, responses: dict[str, list[ClientUpdateObservation]]) -> None:
        self.responses = {channel: list(items) for channel, items in responses.items()}
        self.calls: list[tuple[str, int | None]] = []

    async def get_observation(
        self,
        channel_id: str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        self.calls.append((channel_id, previous_patch_version))
        return self.responses[channel_id].pop(0)


def _observation(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
) -> ClientUpdateObservation:
    snapshot = ClientVersionSnapshot(
        channel_id=channel_id,
        platform=platform,
        region=ClientRegion.CN,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=(
            str(patch_version) if platform is ClientPlatform.ANDROID else None
        ),
        major=1,
        minor=5,
        revamp=patch_version,
        patch_key=1,
    )
    return ClientUpdateObservation(snapshot)


@pytest.mark.asyncio
async def test_real_client_update_handler_adapts_multichannel_result_for_onebot(
    tmp_path: Path,
) -> None:
    """真实 registry handler 应把 service 的多 channel 响应交给平台适配器。"""

    transport = _ChannelTransport(
        {
            "pc_cn": [
                _observation("pc_cn", ClientPlatform.PC, 192),
                _observation("pc_cn", ClientPlatform.PC, 192),
            ],
            "android_astc_cn": [
                _observation("android_astc_cn", ClientPlatform.ANDROID, 193),
                _observation("android_astc_cn", ClientPlatform.ANDROID, 193),
            ],
        }
    )
    service = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "client_update_state.json"),
        transport=transport,
        channels=("pc_cn", "android_astc_cn"),
    )

    class GeneratedClientUpdatePlugin:
        __module__ = "tests.generated_goal6_task28_plugin"

    spec = load_command_registry().get("client_update")
    assert spec.name == "客户端更新"
    registry = CommandRegistry((spec,))
    install_command_handlers(GeneratedClientUpdatePlugin, registry)
    plugin = GeneratedClientUpdatePlugin()
    object.__setattr__(
        plugin,
        "_runtime",
        SimpleNamespace(
            commands=registry,
            responses=ResponseFactory(),
            services={"client_update_service": service},
        ),
    )

    handler = cast(Any, plugin).handle_client_update
    assert inspect.isasyncgenfunction(handler)

    onebot_result = [item async for item in handler(_HandlerEvent("aiocqhttp"))]
    ordinary_result = [item async for item in handler(_HandlerEvent("telegram"))]

    assert len(onebot_result) == 1
    assert onebot_result[0][0] == "chain"
    nodes = onebot_result[0][1]
    assert isinstance(nodes, AstrNodes)
    assert len(nodes.nodes) == 2
    assert [node.content[0].text.splitlines()[0] for node in nodes.nodes] == [
        "检测到二重螺旋国服 PC 客户端",
        "检测到二重螺旋国服 安卓 客户端",
    ]

    assert len(ordinary_result) == 1
    assert ordinary_result[0][0] == "plain"
    assert ordinary_result[0][1].count("\n\n") == 1
    assert "检测到二重螺旋国服 PC 客户端" in ordinary_result[0][1]
    assert "检测到二重螺旋国服 安卓 客户端" in ordinary_result[0][1]
    assert transport.calls == [
        ("pc_cn", None),
        ("android_astc_cn", None),
        ("pc_cn", None),
        ("android_astc_cn", None),
    ]
