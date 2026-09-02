"""Goal 3 / Task 16：客户端更新 fake API 与跨实例持久化回归。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeAlias

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
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
)

_FakeApiResult: TypeAlias = ClientUpdateObservation | BaseException


def _actor(group_id: str) -> EventActor:
    return EventActor(
        user_id=f"admin-{group_id}",
        bot_id="123456",
        group_id=group_id,
        unified_msg_origin=f"aiocqhttp:group:{group_id}",
    )


def _snapshot(platform: ClientPlatform, patch_version: int) -> ClientVersionSnapshot:
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
    )


def _observation(
    platform: ClientPlatform,
    patch_version: int,
    *,
    patch_sizes: dict[int, int] | None = None,
) -> ClientUpdateObservation:
    return ClientUpdateObservation(
        snapshot=_snapshot(platform, patch_version),
        patch_sizes=patch_sizes or {},
    )


class _FakeClientUpdateApi:
    """按平台顺序返回 fake API 观察结果或可分类的失败。"""

    def __init__(self, responses: dict[ClientPlatform, list[_FakeApiResult]]) -> None:
        self._responses = {
            platform: list(items) for platform, items in responses.items()
        }
        self.calls: list[tuple[ClientPlatform, int | None]] = []

    async def get_observation(
        self,
        platform: ClientPlatform | str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        normalized = ClientPlatform(platform)
        self.calls.append((normalized, previous_patch_version))
        result = self._responses[normalized].pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _service(
    root: Path,
    api: _FakeClientUpdateApi,
) -> tuple[ClientUpdateService, SubscriptionStore, ClientUpdateStateStore]:
    subscriptions = SubscriptionStore(root / "subscriptions.json")
    state = ClientUpdateStateStore(root / "client_update_state.json")
    return (
        ClientUpdateService(state, transport=api, subscriptions=subscriptions),
        subscriptions,
        state,
    )


def _request(group_id: str, *platforms: ClientPlatform) -> ClientUpdateRequest:
    return ClientUpdateRequest(actor=_actor(group_id), platforms=platforms)


def _network_failure(resource: str) -> ClientUpdateTransportError:
    return ClientUpdateTransportError(
        ClientUpdateFailureKind.NETWORK,
        resource=resource,
        detail="secret-provider-detail",
    )


@pytest.mark.asyncio
async def test_fake_api_rounds_keep_platform_failures_isolated_and_reload_state(
    tmp_path: Path,
) -> None:
    """首次订阅建基线，多轮检查分别失败时仍保留成功平台和持久化状态。"""

    api = _FakeClientUpdateApi(
        {
            ClientPlatform.PC: [
                _observation(ClientPlatform.PC, 100),
                _network_failure("pc-version-list"),
                _observation(
                    ClientPlatform.PC,
                    102,
                    patch_sizes={101: 10, 102: 20},
                ),
            ],
            ClientPlatform.ANDROID: [
                _observation(ClientPlatform.ANDROID, 200),
                _observation(
                    ClientPlatform.ANDROID,
                    201,
                    patch_sizes={201: 30},
                ),
                _network_failure("android-version-list"),
            ],
        }
    )
    service, subscriptions, state = _service(tmp_path, api)

    response = await service.subscribe(
        _request("group-1", ClientPlatform.PC, ClientPlatform.ANDROID)
    )

    assert "成功" in response.text
    assert api.calls == [
        (ClientPlatform.PC, None),
        (ClientPlatform.ANDROID, None),
    ]
    stored = await subscriptions.list_all()
    assert len(stored) == 1
    assert json.loads(stored[0].extra_data) == {
        "platforms": [ClientPlatform.PC.value, ClientPlatform.ANDROID.value]
    }

    assert await service.poll_now() == 1
    pc_after_pc_failure = await state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    android_after_success = await state.get_baseline(
        ClientRegion.CN,
        ClientPlatform.ANDROID,
    )
    assert pc_after_pc_failure is not None
    assert pc_after_pc_failure.snapshot.patch_version == 100
    assert pc_after_pc_failure.last_change is None
    assert android_after_success is not None
    assert android_after_success.snapshot.patch_version == 201
    assert android_after_success.last_change is not None
    assert android_after_success.last_change.added_size_bytes == 30

    assert await service.poll_now() == 1
    pc_after_success = await state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    android_after_android_failure = await state.get_baseline(
        ClientRegion.CN,
        ClientPlatform.ANDROID,
    )
    assert pc_after_success is not None
    assert pc_after_success.snapshot.patch_version == 102
    assert pc_after_success.last_change is not None
    assert pc_after_success.last_change.added_size_bytes == 30
    assert android_after_android_failure == android_after_success
    assert api.calls == [
        (ClientPlatform.PC, None),
        (ClientPlatform.ANDROID, None),
        (ClientPlatform.PC, 100),
        (ClientPlatform.ANDROID, 200),
        (ClientPlatform.PC, 100),
        (ClientPlatform.ANDROID, 201),
    ]

    reloaded_state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    reloaded_subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    restored_pc = await reloaded_state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
    restored_android = await reloaded_state.get_baseline(
        ClientRegion.CN,
        ClientPlatform.ANDROID,
    )
    assert restored_pc == pc_after_success
    assert restored_android == android_after_android_failure
    assert await reloaded_subscriptions.list_all() == stored


@pytest.mark.asyncio
async def test_multiple_groups_cancel_and_resubscribe_without_resetting_global_baseline(
    tmp_path: Path,
) -> None:
    """多个群独立保存筛选；取消后重订阅不删除全局基线，也不重复请求 API。"""

    api = _FakeClientUpdateApi(
        {
            ClientPlatform.PC: [_observation(ClientPlatform.PC, 100)],
            ClientPlatform.ANDROID: [_observation(ClientPlatform.ANDROID, 200)],
        }
    )
    service, subscriptions, state = _service(tmp_path, api)

    await service.subscribe(_request("group-1", ClientPlatform.PC))
    await service.subscribe(_request("group-2", ClientPlatform.ANDROID))

    initial_subscriptions = await subscriptions.list_all()
    assert {subscription.group_id for subscription in initial_subscriptions} == {
        "group-1",
        "group-2",
    }
    assert api.calls == [
        (ClientPlatform.PC, None),
        (ClientPlatform.ANDROID, None),
    ]

    cancelled = await service.unsubscribe(_request("group-1", ClientPlatform.PC))
    assert "取消" in cancelled.text
    assert [
        subscription.group_id for subscription in await subscriptions.list_all()
    ] == ["group-2"]
    assert await state.get_baseline(ClientRegion.CN, ClientPlatform.PC) is not None

    reloaded_service, reloaded_subscriptions, reloaded_state = _service(
        tmp_path,
        _FakeClientUpdateApi(
            {
                ClientPlatform.PC: [],
                ClientPlatform.ANDROID: [],
            }
        ),
    )
    response = await reloaded_service.subscribe(
        _request("group-1", ClientPlatform.ANDROID)
    )

    assert "成功" in response.text
    restored_subscriptions = await reloaded_subscriptions.list_all()
    assert {
        (
            subscription.group_id,
            tuple(json.loads(subscription.extra_data)["platforms"]),
        )
        for subscription in restored_subscriptions
    } == {
        ("group-1", (ClientPlatform.ANDROID.value,)),
        ("group-2", (ClientPlatform.ANDROID.value,)),
    }
    assert (
        await reloaded_state.get_baseline(ClientRegion.CN, ClientPlatform.PC)
        is not None
    )
    assert (
        await reloaded_state.get_baseline(ClientRegion.CN, ClientPlatform.ANDROID)
        is not None
    )
