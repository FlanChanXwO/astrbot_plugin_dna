"""Goal 6 T14：channel registry、独立 poll 与订阅适配的 Green 契约。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest
from pydantic import ValidationError

import src.infrastructure.http.client_updates as client_updates_http
from src.bootstrap import build_runtime
from src.infrastructure.client_updates_scheduler import ClientUpdatesScheduler
from src.infrastructure.config import DnabySettings
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.scheduler_state import SchedulerRegistry
from src.modules.client_updates import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateObservation,
    ClientUpdateService,
    ClientUpdateStateStore,
    ClientVersionSnapshot,
)

PC_MAIN = "http://pan01-1-eo.shyxhy.com"
ANDROID_MAIN = "https://pan01-1-hs.shyxhy.com"
ANDROID_BRANCH = "Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub"
ANDROID_USER_AGENT = "EM/++UE4+Release-4.27-CL-0 Android/12"


@dataclass(frozen=True, slots=True)
class _Response:
    status: int
    payload: object

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    async def json(self) -> object:
        return self.payload


class _Session:
    def __init__(self, routes: Mapping[str, _Response]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append((url, kwargs.get("headers") or {}))
        return self.routes[url]


def _version_entry(
    patch_version: int,
    *,
    revamp: int,
    patch_key: int = 1,
) -> dict[str, int]:
    return {
        "major": 1,
        "minor": 5,
        "revamp": revamp,
        "patchKey": patch_key,
        "patchVersion": patch_version,
    }


def _version_list(entries: Mapping[str, Mapping[str, int]]) -> dict[str, object]:
    return {"versionList": dict(entries)}


def _snapshot(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
) -> ClientVersionSnapshot:
    return ClientVersionSnapshot(
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


def _observation(
    channel_id: str,
    platform: ClientPlatform,
    patch_version: int,
    *,
    patch_sizes: Mapping[int, int] | None = None,
) -> ClientUpdateObservation:
    return ClientUpdateObservation(
        snapshot=_snapshot(channel_id, platform, patch_version),
        patch_sizes=patch_sizes or {},
    )


class _ChannelTransport:
    def __init__(
        self,
        responses: Mapping[str, Sequence[ClientUpdateObservation | BaseException]],
    ) -> None:
        self.responses = {channel: list(items) for channel, items in responses.items()}
        self.calls: list[tuple[str, int | None]] = []

    async def get_observation(
        self,
        channel_id: str,
        *,
        previous_patch_version: int | None = None,
    ) -> ClientUpdateObservation:
        self.calls.append((channel_id, previous_patch_version))
        result = self.responses[channel_id].pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.mark.asyncio
async def test_service_polls_configured_channel_ids_and_keeps_channel_baselines_separate(
    tmp_path: Path,
) -> None:
    """poll 必须按配置 channel ID 工作，并为每个 channel 维护独立基线。"""

    transport = _ChannelTransport(
        {
            "pc_cn": [
                _observation("pc_cn", ClientPlatform.PC, 100),
                _observation("pc_cn", ClientPlatform.PC, 101, patch_sizes={101: 11}),
            ],
            "android_astc_cn": [
                _observation("android_astc_cn", ClientPlatform.ANDROID, 200),
                _observation(
                    "android_astc_cn",
                    ClientPlatform.ANDROID,
                    201,
                    patch_sizes={201: 22},
                ),
            ],
        }
    )
    state = ClientUpdateStateStore(tmp_path / "client_update_state.json")
    service = ClientUpdateService(
        state,
        transport=transport,
        channels=("pc_cn", "android_astc_cn"),
    )

    assert await service.poll_now() == ()
    changes = await service.poll_now()

    assert [change.channel_id for change in changes] == [
        "pc_cn",
        "android_astc_cn",
    ]
    assert [change.added_size_bytes for change in changes] == [11, 22]
    assert transport.calls == [
        ("pc_cn", None),
        ("android_astc_cn", None),
        ("pc_cn", 100),
        ("android_astc_cn", 200),
    ]
    pc_baseline = await state.get_baseline(ClientRegion.CN, "pc_cn")
    android_baseline = await state.get_baseline(
        ClientRegion.CN,
        "android_astc_cn",
    )
    assert pc_baseline is not None
    assert android_baseline is not None
    assert pc_baseline.snapshot.channel_id == "pc_cn"
    assert android_baseline.snapshot.channel_id == "android_astc_cn"


@pytest.mark.asyncio
async def test_transport_accepts_channel_id_and_uses_registry_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transport 的公开入口应接受 channel ID，而不是要求调用方拼协议细节。"""

    version_url = f"{ANDROID_MAIN}/{ANDROID_BRANCH}/VersionList.json"
    session = _Session(
        {
            version_url: _Response(
                200,
                _version_list({"1010165": _version_entry(201, revamp=193)}),
            )
        }
    )
    monkeypatch.setattr(client_updates_http.aiohttp, "ClientSession", lambda: session)

    observation = await client_updates_http.ClientUpdateTransport().get_observation(
        "android_astc_cn"
    )

    assert observation.snapshot.channel_id == "android_astc_cn"
    assert observation.snapshot.platform is ClientPlatform.ANDROID
    assert session.requests == [(version_url, {"User-Agent": ANDROID_USER_AGENT})]


def test_client_update_settings_validate_registry_ids_and_bootstrap_uses_new_group(
    tmp_path: Path,
) -> None:
    """配置校验和 bootstrap 应使用 client_updates 分组，不读取旧通知开关。"""

    settings = DnabySettings.from_config(
        {
            "client_updates": {
                "enabled": False,
                "check_minutes": 17,
                "channels": ["pc_cn"],
                "merge_forward": False,
            }
        }
    )
    assert settings.client_updates.channels == ["pc_cn"]
    with pytest.raises(ValidationError):
        DnabySettings.from_config({"client_updates": {"channels": ["not-registered"]}})

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {
            "client_updates": {
                "enabled": False,
                "check_minutes": 17,
                "channels": ["pc_cn"],
                "merge_forward": False,
            }
        },
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
        client_updates_transport=object(),
    )

    service = runtime.services["client_update_service"]
    scheduler = runtime.services["client_updates_scheduler"]
    adapter = runtime.services["client_update_push_adapter"]
    assert service.channels == ("pc_cn",)
    assert scheduler.enabled is False
    assert scheduler.check_minutes == 17
    assert adapter.merge_forward is False


class _OrderedSource:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.polled = asyncio.Event()

    async def poll_now(self) -> tuple[Any, ...]:
        self.order.append("poll")
        self.polled.set()
        return ()


class _OrderedDelivery:
    async def deliver(self, _changes: Sequence[Any]) -> int:
        return 0


class _OrderedSleep:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls = 0
        self.release = asyncio.Event()

    async def __call__(self, _seconds: float) -> None:
        self.calls += 1
        self.order.append("sleep")
        if self.calls > 1:
            await self.release.wait()


@pytest.mark.asyncio
async def test_scheduler_polls_immediately_before_waiting_for_first_interval(
    tmp_path: Path,
) -> None:
    """scheduler 启动后应先 poll 建立基线，再等待下一周期。"""

    order: list[str] = []
    source = _OrderedSource(order)
    scheduler = ClientUpdatesScheduler(
        source,
        _OrderedDelivery(),
        registry=SchedulerRegistry(tmp_path / "scheduler_state.json"),
        sleep=_OrderedSleep(order),
    )

    await scheduler.start()
    await source.polled.wait()
    assert order[0] == "poll"
    await scheduler.stop()
