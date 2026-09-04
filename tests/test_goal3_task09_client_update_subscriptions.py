"""Goal 3 / Task 09：客户端更新订阅与命令 registry 的 Red 契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.entry.commands import CommandRegistry, CommandRequest
from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
)
from src.modules.client_updates import commands as client_update_commands

CLIENT_UPDATE_SUBSCRIPTION_TYPE = "订阅DNA客户端更新"


def _actor(
    *,
    user_id: str = "user-1",
    group_id: str | None = "group-1",
    origin: str | None = "platform:group:group-1",
) -> EventActor:
    return EventActor(
        user_id=user_id,
        bot_id="onebot",
        group_id=group_id,
        unified_msg_origin=origin,
    )


def _snapshot(
    platform: ClientPlatform, patch_version: int = 100
) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
        platform=platform,
        version_key=patch_version,
        patch_version=patch_version,
        resource_version_dir=(
            str(patch_version) if platform is ClientPlatform.ANDROID else None
        ),
        major=1,
        minor=5,
        revamp=patch_version,
        patch_key=1,
        region=ClientRegion.CN,
    )


class _FakeClientUpdateTransport:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[tuple[ClientPlatform, int | None]] = []

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        normalized_platform = ClientPlatform(platform)
        self.calls.append((normalized_platform, previous_patch_version))
        if self.error is not None:
            raise self.error
        return ClientUpdateObservation(snapshot=_snapshot(normalized_platform))


class _RecordingQueryService:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def query(self, request: Any) -> PlainTextResponse:
        self.requests.append(request)
        return PlainTextResponse("query-ok")


def _registry() -> CommandRegistry:
    return CommandRegistry(client_update_commands.COMMAND_SPECS)


def _match(registry: CommandRegistry, text: str):
    matched = registry.match(text)
    assert matched is not None, f"未注册命令：{text}"
    return matched


async def _invoke(
    registry: CommandRegistry,
    text: str,
    *,
    actor: EventActor,
    permission: str,
    services: dict[str, object],
):
    matched = _match(registry, text)
    request = CommandRequest(
        command_id=matched.command.id,
        text=text,
        parameters=matched.parameters,
        actor=actor,
        permission=permission,
        services=services,
    )
    return await matched.command.use_case(request, registry, **matched.parameters)


def _build_service(
    root: Path,
    transport: _FakeClientUpdateTransport,
) -> tuple[ClientUpdateService, SubscriptionStore, ClientUpdateStateStore]:
    subscriptions = SubscriptionStore(root / "subscriptions.json")
    state = ClientUpdateStateStore(root / "client_update_state.json")
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
    )
    return service, subscriptions, state


def test_client_update_command_registry_declares_query_and_admin_subscription_surface():
    """查询是 user 权限；订阅/取消订阅是 admin 权限，且支持默认与平台筛选。"""

    registry = _registry()

    query_matches = [
        _match(registry, "客户端更新"),
        _match(registry, "客户端更新 PC"),
        _match(registry, "客户端更新 安卓"),
    ]
    assert all(item.command.permission == "user" for item in query_matches)

    subscription_matches = [
        _match(registry, "订阅客户端更新"),
        _match(registry, "订阅客户端更新 PC"),
        _match(registry, "订阅客户端更新 安卓"),
        _match(registry, "取消订阅客户端更新"),
    ]
    assert all(item.command.permission == "admin" for item in subscription_matches)


@pytest.mark.asyncio
async def test_client_update_query_passes_normalized_platform_parameters_to_service():
    """查询命令默认选择全部平台，带平台后只传递对应平台。"""

    registry = _registry()
    service = _RecordingQueryService()
    actor = _actor()

    await _invoke(
        registry,
        "客户端更新",
        actor=actor,
        permission="user",
        services={"client_update_service": service},
    )
    await _invoke(
        registry,
        "客户端更新 安卓",
        actor=actor,
        permission="user",
        services={"client_update_service": service},
    )

    assert [request.platforms for request in service.requests] == [
        (ClientPlatform.PC, ClientPlatform.ANDROID),
        (ClientPlatform.ANDROID,),
    ]
    assert all(request.actor == actor for request in service.requests)


@pytest.mark.asyncio
async def test_subscription_requires_group_admin_and_keeps_store_unchanged_for_forbidden_calls(
    tmp_path: Path,
) -> None:
    """私聊或普通群成员不能创建客户端更新订阅。"""

    cases = (
        (_actor(), "user"),
        (
            _actor(
                group_id=None,
                origin="platform:private:user-1",
            ),
            "admin",
        ),
    )
    for index, (actor, permission) in enumerate(cases):
        transport = _FakeClientUpdateTransport()
        service, subscriptions, _state = _build_service(
            tmp_path / str(index), transport
        )

        response = await _invoke(
            _registry(),
            "订阅客户端更新",
            actor=actor,
            permission=permission,
            services={"client_update_service": service},
        )

        assert isinstance(response, PlainTextResponse)
        assert await subscriptions.list_all() == ()
        assert transport.calls == []


@pytest.mark.asyncio
async def test_subscription_saves_platform_filter_and_dedupes_same_group_target(
    tmp_path: Path,
) -> None:
    """群管理员订阅按平台保存，重复订阅不产生第二个目标。"""

    transport = _FakeClientUpdateTransport()
    service, subscriptions, _state = _build_service(tmp_path, transport)
    registry = _registry()
    actor = _actor()
    services = {"client_update_service": service}

    await _invoke(
        registry,
        "订阅客户端更新 PC",
        actor=actor,
        permission="admin",
        services=services,
    )
    duplicate_response = await _invoke(
        registry,
        "订阅客户端更新 PC",
        actor=actor,
        permission="admin",
        services=services,
    )

    stored = await subscriptions.list_all()
    assert len(stored) == 1
    assert stored[0].type == CLIENT_UPDATE_SUBSCRIPTION_TYPE
    assert stored[0].uid == ""
    assert stored[0].unified_msg_origin == actor.unified_msg_origin
    assert json.loads(stored[0].extra_data) == {"platforms": [ClientPlatform.PC.value]}
    assert isinstance(duplicate_response, PlainTextResponse)
    assert "重复" in duplicate_response.text or "已经" in duplicate_response.text


@pytest.mark.asyncio
async def test_default_subscription_stores_all_platforms_and_can_be_cancelled(
    tmp_path: Path,
) -> None:
    """默认订阅包含 PC/安卓，取消后删除当前群目标。"""

    transport = _FakeClientUpdateTransport()
    service, subscriptions, _state = _build_service(tmp_path, transport)
    registry = _registry()
    actor = _actor()
    services = {"client_update_service": service}

    await _invoke(
        registry,
        "订阅客户端更新",
        actor=actor,
        permission="admin",
        services=services,
    )
    assert json.loads((await subscriptions.list_all())[0].extra_data) == {
        "platforms": [ClientPlatform.PC.value, ClientPlatform.ANDROID.value]
    }

    response = await _invoke(
        registry,
        "取消订阅客户端更新",
        actor=actor,
        permission="admin",
        services=services,
    )

    assert isinstance(response, PlainTextResponse)
    assert await subscriptions.get(CLIENT_UPDATE_SUBSCRIPTION_TYPE) == ()


@pytest.mark.asyncio
async def test_failed_initial_subscription_keeps_subscription_for_later_retry(
    tmp_path: Path,
) -> None:
    """首次查询失败时保留订阅，但不能伪造成功基线或泄露 transport 细节。"""

    transport = _FakeClientUpdateTransport(
        ClientUpdateTransportError(
            ClientUpdateFailureKind.NETWORK,
            detail="secret-provider-detail",
        )
    )
    service, subscriptions, state = _build_service(tmp_path, transport)
    actor = _actor()

    response = await _invoke(
        _registry(),
        "订阅客户端更新 PC",
        actor=actor,
        permission="admin",
        services={"client_update_service": service},
    )

    assert isinstance(response, PlainTextResponse)
    assert "secret-provider-detail" not in response.text
    stored = await subscriptions.list_all()
    assert len(stored) == 1
    assert json.loads(stored[0].extra_data) == {"platforms": [ClientPlatform.PC.value]}
    assert await state.get_baseline(ClientRegion.CN, ClientPlatform.PC) is None
