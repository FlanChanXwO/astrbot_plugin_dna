"""客户端更新 service 的 Source 去重与 history-gap 行为测试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    AppStoreProviderConfig,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateBaseline,
    ClientUpdateFailureKind,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
    ClientUpdateRequest,
    ClientUpdateService,
    ClientUpdateSource,
    ClientUpdateStateStore,
    ClientUpdateTarget,
    ClientUpdateTransportError,
    messages,
)


def _source_version(
    source_id: str,
    revision_id: str,
    *,
    order_key: int | tuple[int, ...] | None = None,
) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=f"version-{revision_id}",
        revision_id=revision_id,
        order_key=order_key,
    )


@dataclass
class _ReadOnlyState:
    baselines: dict[str, object] = field(default_factory=dict)
    writes: int = 0

    async def get_baseline(self, source_id: str):
        return self.baselines.get(source_id)

    async def save_baseline(self, _baseline) -> None:
        self.writes += 1

    async def save_baseline_with_pending_event(self, *_args):
        self.writes += 1


@dataclass
class _Transport:
    observations: dict[str, ClientSourceObservation | ClientUpdateTransportError]
    calls: list[tuple[str, ClientSourceVersion | None]] = field(default_factory=list)

    async def get_observation(
        self,
        source_id: str,
        *,
        baseline: ClientSourceVersion | None = None,
    ) -> ClientSourceObservation:
        self.calls.append((source_id, baseline))
        result = self.observations[source_id]
        if isinstance(result, ClientUpdateTransportError):
            raise result
        return result


def _shared_source_registry() -> ClientUpdateRegistry:
    source = ClientUpdateSource(
        source_id="shared-source",
        platform=ClientPlatform.IOS,
        provider_kind=ClientUpdateProviderKind.APP_STORE,
        provider_config=AppStoreProviderConfig(track_id=1, country="cn"),
    )
    return ClientUpdateRegistry(
        sources=(source,),
        targets=(
            ClientUpdateTarget(
                target_id="cn-official-ios",
                region_id="cn",
                ecosystem_id="official",
                platform=ClientPlatform.IOS,
                source_id=source.source_id,
                display_name="国服官服 iOS",
            ),
            ClientUpdateTarget(
                target_id="global-official-ios",
                region_id="global",
                ecosystem_id="official",
                platform=ClientPlatform.IOS,
                source_id=source.source_id,
                display_name="全球服官服 iOS",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_query_observes_shared_source_once_and_never_writes_state() -> None:
    registry = _shared_source_registry()
    current = _source_version("shared-source", "1.6.0")
    transport = _Transport(
        {
            "shared-source": ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=True,
                added_size_bytes=None,
            )
        }
    )
    state = _ReadOnlyState()
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-ios", "global-official-ios"),
        registry=registry,
    )

    response = await service.query(
        ClientUpdateRequest(
            actor=EventActor(
                user_id="user-1",
                bot_id="bot-1",
                unified_msg_origin="private:user-1",
            )
        )
    )

    assert transport.calls == [("shared-source", None)]
    assert state.writes == 0
    assert "国服官服 iOS" in response.text
    assert "全球服官服 iOS" in response.text
    assert "version-1.6.0" in response.text


@pytest.mark.asyncio
async def test_query_isolates_one_source_failure_without_writing_state() -> None:
    pc_source = "cn-official-pc-manifest"
    android_source = "cn-official-android-astc-manifest"
    android = _source_version(android_source, "203")
    transport = _Transport(
        {
            pc_source: ClientUpdateTransportError(ClientUpdateFailureKind.NETWORK),
            android_source: ClientSourceObservation(
                current=android,
                observed_versions=(android,),
                history_complete=True,
                added_size_bytes=None,
            ),
        }
    )
    state = _ReadOnlyState()
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc", "cn-official-android"),
    )

    response = await service.query(
        ClientUpdateRequest(
            actor=EventActor(
                user_id="user-1",
                bot_id="bot-1",
                unified_msg_origin="private:user-1",
            )
        )
    )

    assert [source_id for source_id, _baseline in transport.calls] == [
        pc_source,
        android_source,
    ]
    assert state.writes == 0
    assert "国服官服 Android" in response.text
    assert "version-203" in response.text


@pytest.mark.asyncio
async def test_query_returns_overall_unavailable_only_when_every_source_fails() -> None:
    source_ids = (
        "cn-official-pc-manifest",
        "cn-official-android-astc-manifest",
    )
    transport = _Transport(
        {
            source_id: ClientUpdateTransportError(ClientUpdateFailureKind.NETWORK)
            for source_id in source_ids
        }
    )
    service = ClientUpdateService(
        _ReadOnlyState(),
        transport=transport,
        target_ids=("cn-official-pc", "cn-official-android"),
    )

    response = await service.query(
        ClientUpdateRequest(
            actor=EventActor(
                user_id="user-1",
                bot_id="bot-1",
                unified_msg_origin="private:user-1",
            )
        )
    )

    assert response.text == messages.CLIENT_UPDATE_UNAVAILABLE
    assert tuple(source_id for source_id, _baseline in transport.calls) == source_ids


@pytest.mark.asyncio
async def test_query_reports_history_gap_without_advancing_baseline() -> None:
    source_id = "cn-official-pc-manifest"
    previous = _source_version(source_id, "100", order_key=(100, 100))
    current = _source_version(source_id, "103", order_key=(103, 103))
    state = _ReadOnlyState(
        baselines={
            source_id: ClientUpdateBaseline(
                version=previous,
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            )
        }
    )
    transport = _Transport(
        {
            source_id: ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=False,
                added_size_bytes=None,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc",),
    )

    response = await service.query(
        ClientUpdateRequest(
            actor=EventActor(
                user_id="user-1",
                bot_id="bot-1",
                unified_msg_origin="private:user-1",
            )
        )
    )

    assert state.writes == 0
    assert "version-100 → version-103" in response.text
    assert "大小未知（历史窗口已变化）" in response.text


@pytest.mark.asyncio
async def test_poll_history_gap_advances_atomically_and_does_not_repeat(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    target_ids = ("cn-official-pc",)
    previous = _source_version(source_id, "100", order_key=(100, 100))
    current = _source_version(source_id, "103", order_key=(103, 103))
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await state.save_baseline(
        ClientUpdateBaseline(
            version=previous,
            observed_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin="group:1",
        bot_id="bot-1",
        extra_data="{}",
    )
    transport = _Transport(
        {
            source_id: ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=False,
                added_size_bytes=None,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
        target_ids=target_ids,
    )

    first_changes = await service.poll_now()
    first_pending = await state.pending_events()
    second_changes = await service.poll_now()

    assert len(first_changes) == 1
    assert first_changes[0].history_complete is False
    assert first_changes[0].target_ids == target_ids
    assert await state.get_baseline(source_id) == ClientUpdateBaseline(
        version=current,
        observed_at=(await state.get_baseline(source_id)).observed_at,
        last_change=first_changes[0],
    )
    assert len(first_pending) == 1
    assert first_pending[0].targets[0].target_ids == target_ids
    assert second_changes == ()
    assert await state.pending_events() == first_pending
    assert [baseline.revision_id for _source, baseline in transport.calls] == [
        "100",
        "103",
    ]


@pytest.mark.asyncio
async def test_poll_isolates_one_source_failure_and_keeps_other_change() -> None:
    pc_source = "cn-official-pc-manifest"
    android_source = "cn-official-android-astc-manifest"
    pc_previous = _source_version(pc_source, "100", order_key=(100, 100))
    android_previous = _source_version(
        android_source,
        "200",
        order_key=(200, 200),
    )
    android_current = _source_version(
        android_source,
        "201",
        order_key=(201, 201),
    )
    state = _ReadOnlyState(
        baselines={
            pc_source: ClientUpdateBaseline(
                version=pc_previous,
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            ),
            android_source: ClientUpdateBaseline(
                version=android_previous,
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            ),
        }
    )
    transport = _Transport(
        {
            pc_source: ClientUpdateTransportError(ClientUpdateFailureKind.NETWORK),
            android_source: ClientSourceObservation(
                current=android_current,
                observed_versions=(android_previous, android_current),
                history_complete=True,
                added_size_bytes=4096,
            ),
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc", "cn-official-android"),
    )

    changes = await service.poll_now()

    assert tuple(change.source_id for change in changes) == (android_source,)
    assert changes[0].added_size_bytes == 4096
    assert state.writes == 1


@pytest.mark.asyncio
async def test_concurrent_polls_are_serialized_before_reading_source_baseline(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await state.save_baseline(
        ClientUpdateBaseline(
            version=_source_version(source_id, "100", order_key=(100, 100)),
            observed_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class ConcurrentTransport:
        def __init__(self) -> None:
            self.baselines: list[str] = []
            self.active = 0
            self.max_active = 0

        async def get_observation(
            self,
            _source_id: str,
            *,
            baseline: ClientSourceVersion | None = None,
        ) -> ClientSourceObservation:
            assert baseline is not None
            self.baselines.append(baseline.revision_id)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if len(self.baselines) == 1:
                first_started.set()
                await release_first.wait()
            next_revision = str(int(baseline.revision_id) + 2)
            current = _source_version(
                source_id,
                next_revision,
                order_key=(int(next_revision), int(next_revision)),
            )
            self.active -= 1
            return ClientSourceObservation(
                current=current,
                observed_versions=(baseline, current),
                history_complete=True,
                added_size_bytes=1024,
            )

    transport = ConcurrentTransport()
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc",),
    )

    first_poll = asyncio.create_task(service.poll_now())
    await first_started.wait()
    second_poll = asyncio.create_task(service.poll_now())
    await asyncio.sleep(0)
    release_first.set()
    first_changes, second_changes = await asyncio.gather(first_poll, second_poll)

    assert transport.max_active == 1
    assert transport.baselines == ["100", "102"]
    assert tuple(change.current.revision_id for change in first_changes) == ("102",)
    assert tuple(change.current.revision_id for change in second_changes) == ("104",)
    baseline = await state.get_baseline(source_id)
    assert baseline is not None
    assert baseline.version.revision_id == "104"


@pytest.mark.asyncio
async def test_poll_rejects_reliable_rollback_without_writing_state() -> None:
    source_id = "cn-official-pc-manifest"
    previous = _source_version(source_id, "103", order_key=(103, 103))
    current = _source_version(source_id, "102", order_key=(102, 102))
    baseline = ClientUpdateBaseline(
        version=previous,
        observed_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    state = _ReadOnlyState(baselines={source_id: baseline})
    transport = _Transport(
        {
            source_id: ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=False,
                added_size_bytes=None,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-pc",),
    )

    assert await service.poll_now() == ()
    assert state.writes == 0
    assert await state.get_baseline(source_id) == baseline


@pytest.mark.asyncio
async def test_poll_observes_shared_source_once() -> None:
    registry = _shared_source_registry()
    current = _source_version("shared-source", "1.6.0")
    transport = _Transport(
        {
            "shared-source": ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=True,
                added_size_bytes=None,
            )
        }
    )
    state = _ReadOnlyState()
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-ios", "global-official-ios"),
        registry=registry,
    )

    assert await service.poll_now() == ()
    assert transport.calls == [("shared-source", None)]
    assert state.writes == 1
