"""Goal 6 / Task 16：客户端查询输出与 OneBot/非 OneBot 适配契约。"""

from __future__ import annotations

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
from src.entry.event import EventActor
from src.entry.response import MultiTextResponse, PlainTextResponse, ResponseFactory
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateRequest,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
    messages,
)


class _ResponseEvent:
    """只实现 ResponseFactory 需要的结果构造与平台识别接口。"""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    def get_platform_name(self) -> str:
        return self.platform_name

    def plain_result(self, text: str) -> tuple[str, str]:
        return ("plain", text)

    def chain_result(self, components: object) -> tuple[str, object]:
        return ("chain", components)


def _actor() -> EventActor:
    return EventActor(
        user_id="user-1",
        bot_id="bot-1",
        group_id="group-1",
        unified_msg_origin="aiocqhttp:group:group-1",
    )


def _snapshot(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
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
        channel_id=channel_id,
    )


def _observation(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
) -> ClientUpdateObservation:
    return ClientUpdateObservation(_snapshot(channel_id, platform, patch_version))


class _QueryTransport:
    """按固定 channel ID 返回观察结果并记录只读查询参数。"""

    def __init__(
        self, responses: dict[str, list[ClientUpdateObservation | BaseException]]
    ):
        self.responses = {channel: list(items) for channel, items in responses.items()}
        self.calls: list[tuple[str, int | None]] = []

    async def get_observation(
        self,
        target: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        channel_id = str(target)
        self.calls.append((channel_id, previous_patch_version))
        result = self.responses[channel_id].pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _network_failure(channel_id: str) -> ClientUpdateTransportError:
    return ClientUpdateTransportError(
        ClientUpdateFailureKind.NETWORK,
        resource=channel_id,
        detail="private transport detail",
    )


def _service(
    root: Path,
    transport: _QueryTransport,
) -> ClientUpdateService:
    return ClientUpdateService(
        ClientUpdateStateStore(root / "client_update_state.json"),
        transport=transport,
        channels=("pc_cn", "android_astc_cn"),
    )


def test_multi_text_response_preserves_order_and_rejects_empty_result() -> None:
    """多文本 DTO 只承载有序文本；空结果必须显式失败而非静默发送空消息。"""

    response = MultiTextResponse(("国服 PC", "国服安卓"))

    assert response.texts == ("国服 PC", "国服安卓")
    with pytest.raises(ValueError, match="多文本响应至少需要一条文本"):
        MultiTextResponse(())
    with pytest.raises(TypeError, match="多文本响应只能包含字符串"):
        MultiTextResponse(("国服 PC", 1))  # type: ignore[arg-type]


def test_response_factory_adapts_multi_text_for_onebot_and_other_platforms() -> None:
    """OneBot 多 channel 合并为一条 Nodes；其他平台拼接为普通文本。"""

    factory = ResponseFactory()
    response = MultiTextResponse(("pc update", "android update"))

    onebot_result = factory.build(_ResponseEvent("aiocqhttp"), response)
    assert onebot_result[0] == "chain"
    nodes = onebot_result[1]
    assert isinstance(nodes, AstrNodes)
    assert [node.content[0].text for node in nodes.nodes] == [
        "pc update",
        "android update",
    ]
    assert len(nodes.nodes) == 2

    single_result = factory.build(
        _ResponseEvent("aiocqhttp"),
        MultiTextResponse(("only update",)),
    )
    assert single_result == ("plain", "only update")

    non_onebot_result = factory.build(_ResponseEvent("telegram"), response)
    assert non_onebot_result == ("plain", "pc update\n\nandroid update")


@pytest.mark.asyncio
async def test_query_returns_ordered_multi_text_without_changing_baselines(
    tmp_path: Path,
) -> None:
    """首次多 channel 查询显式标明无 baseline，且查询保持只读。"""

    transport = _QueryTransport(
        {
            "pc_cn": [_observation("pc_cn", ClientPlatform.PC, 192)],
            "android_astc_cn": [
                _observation("android_astc_cn", ClientPlatform.ANDROID, 193)
            ],
        }
    )
    service = _service(tmp_path, transport)

    response = await service.query(
        ClientUpdateRequest(
            actor=_actor(),
            platforms=(ClientPlatform.PC, ClientPlatform.ANDROID),
        )
    )

    assert isinstance(response, MultiTextResponse)
    assert [text.splitlines()[0] for text in response.texts] == [
        "检测到二重螺旋国服 PC 客户端",
        "检测到二重螺旋国服 安卓 客户端",
    ]
    assert all("上次版本：暂无" in text for text in response.texts)
    assert all("新增更新：暂无可比较大小" in text for text in response.texts)
    assert transport.calls == [("pc_cn", None), ("android_astc_cn", None)]
    assert await service.state.get_baseline(ClientRegion.CN, "pc_cn") is None
    assert await service.state.get_baseline(ClientRegion.CN, "android_astc_cn") is None


@pytest.mark.asyncio
async def test_query_single_success_is_plain_and_all_failures_use_fixed_message(
    tmp_path: Path,
) -> None:
    """单 channel 成功走普通消息；全失败返回固定不可用文案且不泄漏错误详情。"""

    single_transport = _QueryTransport(
        {"pc_cn": [_observation("pc_cn", ClientPlatform.PC, 192)]}
    )
    single_service = _service(tmp_path / "single", single_transport)
    single_response = await single_service.query(
        ClientUpdateRequest(actor=_actor(), platforms=(ClientPlatform.PC,))
    )
    assert isinstance(single_response, PlainTextResponse)
    assert "检测到二重螺旋国服 PC 客户端" in single_response.text

    failed_transport = _QueryTransport(
        {
            "pc_cn": [_network_failure("pc_cn-secret")],
            "android_astc_cn": [_network_failure("android-secret")],
        }
    )
    failed_service = _service(tmp_path / "failed", failed_transport)
    failed_response = await failed_service.query(
        ClientUpdateRequest(
            actor=_actor(),
            platforms=(ClientPlatform.PC, ClientPlatform.ANDROID),
        )
    )

    assert failed_response == PlainTextResponse(messages.CLIENT_UPDATE_UNAVAILABLE)
    assert "secret" not in failed_response.text


@pytest.mark.asyncio
async def test_client_update_handler_keeps_command_name_and_async_generator_boundary() -> (
    None
):
    """真实 registry handler 继续二次匹配，并把 MultiTextResponse 交给 adapter。"""

    class FakeClientUpdateService:
        async def query(self, _request: ClientUpdateRequest) -> Any:
            return MultiTextResponse(("pc update", "android update"))

    class GeneratedClientUpdatePlugin:
        __module__ = "tests.generated_client_update_plugin"

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
            services={"client_update_service": FakeClientUpdateService()},
        ),
    )

    class Event:
        def __init__(self, message: str) -> None:
            self.message = message

        def get_message_str(self) -> str:
            return self.message

        def get_sender_id(self) -> str:
            return "user-1"

        def get_self_id(self) -> str:
            return "bot-1"

        def get_group_id(self) -> str:
            return "group-1"

        def get_messages(self) -> list[object]:
            return []

        def plain_result(self, text: str) -> str:
            return text

    handler = cast(Any, plugin).handle_client_update
    result = [item async for item in handler(Event("kk客户端更新"))]
    unmatched = [item async for item in handler(Event("kk客户端更新 安卓 额外"))]

    assert result == ["pc update\n\nandroid update"]
    assert unmatched == []
