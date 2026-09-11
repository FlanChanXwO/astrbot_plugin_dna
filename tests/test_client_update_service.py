"""客户端更新 service 的 Source 去重与 history-gap 行为测试。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.entry.event import EventActor
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.client_updates import (
    AppStoreProviderConfig,
    AppStoreVersionMetadata,
    ClientPlatform,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateBaseline,
    ClientUpdateChange,
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
    provider_metadata: AppStoreVersionMetadata | None = None,
) -> ClientSourceVersion:
    return ClientSourceVersion(
        source_id=source_id,
        version_text=f"version-{revision_id}",
        revision_id=revision_id,
        order_key=order_key,
        provider_metadata=provider_metadata,
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
                target_id="cn-app-store-ios",
                region_id="cn",
                distribution_id="official",
                platform=ClientPlatform.IOS,
                source_id=source.source_id,
                display_name="国服官服 iOS",
            ),
            ClientUpdateTarget(
                target_id="global-app-store-ios-fixture",
                region_id="global",
                distribution_id="official",
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
        target_ids=("cn-app-store-ios", "global-app-store-ios-fixture"),
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
    assert first_pending[0].change.target_ids == target_ids
    assert second_changes == ()
    assert await state.pending_events() == first_pending
    assert [baseline.revision_id for _source, baseline in transport.calls] == [
        "100",
        "103",
    ]


@pytest.mark.asyncio
async def test_poll_same_revision_refreshes_app_store_metadata_and_last_change(
    tmp_path,
) -> None:
    source_id = "cn-official-ios-app-store"
    target_ids = ("cn-app-store-ios",)
    previous = _source_version(
        source_id,
        "6470771372:1.5.0",
        order_key="1.5.0",
        provider_metadata=AppStoreVersionMetadata(
            track_id=6470771372,
            country="cn",
            release_date="2026-08-01T00:00:00Z",
        ),
    )
    baseline_version = _source_version(
        source_id,
        "6470771372:1.6.0",
        order_key="1.6.0",
        provider_metadata=AppStoreVersionMetadata(
            track_id=6470771372,
            country="cn",
            release_date=None,
        ),
    )
    last_change = ClientUpdateChange(
        previous=previous,
        current=baseline_version,
        history_complete=True,
        added_size_bytes=0,
        target_ids=target_ids,
    )
    refreshed_version = _source_version(
        source_id,
        "6470771372:1.6.0",
        order_key="1.6.0",
        provider_metadata=AppStoreVersionMetadata(
            track_id=6470771372,
            country="cn",
            release_date="2026-09-08T00:00:00Z",
        ),
    )
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await state.save_baseline(
        ClientUpdateBaseline(
            version=baseline_version,
            observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            last_change=last_change,
        )
    )
    transport = _Transport(
        {
            source_id: ClientSourceObservation(
                current=refreshed_version,
                observed_versions=(refreshed_version,),
                history_complete=True,
                added_size_bytes=None,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=target_ids,
    )

    assert await service.poll_now() == ()

    refreshed_baseline = await state.get_baseline(source_id)
    assert refreshed_baseline is not None
    assert refreshed_baseline.version == refreshed_version
    assert refreshed_baseline.last_change == ClientUpdateChange(
        previous=previous,
        current=refreshed_version,
        history_complete=True,
        added_size_bytes=0,
        target_ids=target_ids,
    )
    assert await state.pending_events() == ()


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
async def test_subscribe_waits_for_poll_initial_baseline_and_rechecks_after_lock(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    current = _source_version(source_id, "100", order_key=(100, 100))
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class BlockingTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ClientSourceVersion | None]] = []

        async def get_observation(
            self,
            requested_source_id: str,
            *,
            baseline: ClientSourceVersion | None = None,
        ) -> ClientSourceObservation:
            self.calls.append((requested_source_id, baseline))
            if len(self.calls) == 1:
                first_started.set()
                await release_first.wait()
            return ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=True,
                added_size_bytes=None,
            )

    transport = BlockingTransport()
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
        target_ids=("cn-official-pc",),
    )

    poll_task = asyncio.create_task(service.poll_now())
    await first_started.wait()
    subscribe_task = asyncio.create_task(
        service.subscribe(ClientUpdateRequest(actor=_group_actor()))
    )
    await asyncio.sleep(0)

    assert not subscribe_task.done()
    release_first.set()
    changes, response = await asyncio.gather(poll_task, subscribe_task)

    assert changes == ()
    assert response.text == messages.CLIENT_UPDATE_SUBSCRIBED
    assert transport.calls == [(source_id, None)]
    baseline = await state.get_baseline(source_id)
    assert baseline is not None
    assert baseline.version == current
    assert await state.pending_events() == ()


@pytest.mark.asyncio
async def test_poll_waits_for_subscribe_initial_baseline_and_reuses_it(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    current = _source_version(source_id, "100", order_key=(100, 100))
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    initialization_started = asyncio.Event()
    release_initialization = asyncio.Event()

    class BlockingTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ClientSourceVersion | None]] = []

        async def get_observation(
            self,
            requested_source_id: str,
            *,
            baseline: ClientSourceVersion | None = None,
        ) -> ClientSourceObservation:
            self.calls.append((requested_source_id, baseline))
            if len(self.calls) == 1:
                initialization_started.set()
                await release_initialization.wait()
            return ClientSourceObservation(
                current=current,
                observed_versions=(current,),
                history_complete=True,
                added_size_bytes=None,
            )

    transport = BlockingTransport()
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
        target_ids=("cn-official-pc",),
    )

    subscribe_task = asyncio.create_task(
        service.subscribe(ClientUpdateRequest(actor=_group_actor()))
    )
    await initialization_started.wait()
    poll_task = asyncio.create_task(service.poll_now())
    await asyncio.sleep(0)

    assert not poll_task.done()
    release_initialization.set()
    response, changes = await asyncio.gather(subscribe_task, poll_task)

    assert response.text == messages.CLIENT_UPDATE_SUBSCRIBED
    assert changes == ()
    assert transport.calls == [(source_id, None), (source_id, current)]
    baseline = await state.get_baseline(source_id)
    assert baseline is not None
    assert baseline.version == current
    assert await state.pending_events() == ()


@pytest.mark.asyncio
async def test_subscribe_does_not_receive_change_already_in_flight_before_subscription(
    tmp_path,
) -> None:
    pc_source = "cn-official-pc-manifest"
    android_source = "cn-official-android-astc-manifest"
    pc_previous = _source_version(pc_source, "100", order_key=(100, 100))
    pc_current = _source_version(pc_source, "101", order_key=(101, 101))
    pc_next = _source_version(pc_source, "102", order_key=(102, 102))
    android_current = _source_version(
        android_source,
        "200",
        order_key=(200, 200),
    )
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    await state.save_baseline(
        ClientUpdateBaseline(
            version=pc_previous,
            observed_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    poll_started = asyncio.Event()
    release_poll = asyncio.Event()

    class ConcurrentTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ClientSourceVersion | None]] = []

        async def get_observation(
            self,
            source_id: str,
            *,
            baseline: ClientSourceVersion | None = None,
        ) -> ClientSourceObservation:
            self.calls.append((source_id, baseline))
            if source_id == pc_source and baseline == pc_previous:
                poll_started.set()
                await release_poll.wait()
                return ClientSourceObservation(
                    current=pc_current,
                    observed_versions=(pc_previous, pc_current),
                    history_complete=True,
                    added_size_bytes=1024,
                )
            if source_id == pc_source and baseline == pc_current:
                return ClientSourceObservation(
                    current=pc_next,
                    observed_versions=(pc_current, pc_next),
                    history_complete=True,
                    added_size_bytes=1024,
                )
            if source_id == android_source:
                return ClientSourceObservation(
                    current=android_current,
                    observed_versions=(android_current,),
                    history_complete=True,
                    added_size_bytes=None,
                )
            raise AssertionError((source_id, baseline))

    transport = ConcurrentTransport()
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
        target_ids=("cn-official-pc", "cn-official-android"),
    )

    poll_task = asyncio.create_task(service.poll_now())
    await poll_started.wait()
    subscribe_task = asyncio.create_task(
        service.subscribe(ClientUpdateRequest(actor=_group_actor()))
    )
    asyncio.get_running_loop().call_soon(release_poll.set)
    poll_changes, response = await asyncio.gather(poll_task, subscribe_task)

    assert tuple(change.current.revision_id for change in poll_changes) == ("101",)
    assert response.text == messages.CLIENT_UPDATE_SUBSCRIBED
    assert transport.calls == [
        (pc_source, pc_previous),
        (android_source, None),
    ]
    assert await state.pending_events() == ()

    next_changes = await service.poll_now()

    assert tuple(change.current.revision_id for change in next_changes) == ("102",)
    pending = await state.pending_events()
    assert len(pending) == 1
    assert pending[0].change.current == pc_next
    assert tuple(target.origin for target in pending[0].pending_targets) == ("group:1",)


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
        target_ids=("cn-app-store-ios", "global-app-store-ios-fixture"),
        registry=registry,
    )

    assert await service.poll_now() == ()
    assert transport.calls == [("shared-source", None)]
    assert state.writes == 1


@pytest.mark.asyncio
async def test_custom_registry_poll_persists_source_and_target_snapshot(
    tmp_path,
) -> None:
    registry = _shared_source_registry()
    source_id = "shared-source"
    previous = _source_version(source_id, "1.5.0")
    current = _source_version(source_id, "1.6.0")
    state_path = tmp_path / "client_updates.json"
    state = ClientUpdateStateStore(state_path, registry=registry)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
        origin="group:1",
        bot_id="bot-1",
        extra_data="{}",
    )
    await state.save_baseline(
        ClientUpdateBaseline(
            version=previous,
            observed_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    service = ClientUpdateService(
        state,
        transport=_Transport(
            {
                source_id: ClientSourceObservation(
                    current=current,
                    observed_versions=(current,),
                    history_complete=False,
                    added_size_bytes=None,
                )
            }
        ),
        subscriptions=subscriptions,
        target_ids=("cn-app-store-ios", "global-app-store-ios-fixture"),
    )

    changes = await service.poll_now()

    assert len(changes) == 1
    assert changes[0].target_ids == (
        "cn-app-store-ios",
        "global-app-store-ios-fixture",
    )
    reloaded = ClientUpdateStateStore(state_path, registry=registry)
    assert (await reloaded.get_baseline(source_id)).version == current
    pending = await reloaded.pending_events()
    assert len(pending) == 1
    assert pending[0].change.target_ids == (
        "cn-app-store-ios",
        "global-app-store-ios-fixture",
    )


def _group_actor(origin: str = "group:1") -> EventActor:
    return EventActor(
        user_id="admin-1",
        group_id="1",
        bot_id="bot-1",
        unified_msg_origin=origin,
    )


@pytest.mark.asyncio
async def test_subscribe_writes_target_neutral_metadata_and_survives_reload(
    tmp_path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    first = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "client_updates.json"),
        subscriptions=subscriptions,
        target_ids=("cn-official-pc",),
    )

    response = await first.subscribe(ClientUpdateRequest(actor=_group_actor()))
    stored = await subscriptions.get(messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE)

    assert response.text == messages.CLIENT_UPDATE_SUBSCRIBED_RETRY
    assert len(stored) == 1
    assert stored[0].extra_data == "{}"

    reloaded = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "reloaded_state.json"),
        subscriptions=SubscriptionStore(tmp_path / "subscriptions.json"),
        target_ids=("cn-app-store-ios",),
    )
    await reloaded.initialize()

    assert reloaded.target_ids == ("cn-app-store-ios",)
    reloaded_subscriptions = await reloaded.subscriptions.get(
        messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE
    )
    assert reloaded_subscriptions[0].extra_data == "{}"


@pytest.mark.asyncio
async def test_subscribe_with_existing_baseline_defers_source_read_until_poll(
    tmp_path,
) -> None:
    source_id = "cn-official-pc-manifest"
    previous = _source_version(source_id, "100", order_key=(100, 100))
    current = _source_version(source_id, "101", order_key=(101, 101))
    state = ClientUpdateStateStore(tmp_path / "client_updates.json")
    baseline = ClientUpdateBaseline(
        version=previous,
        observed_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    await state.save_baseline(baseline)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    transport = _Transport(
        {
            source_id: ClientSourceObservation(
                current=current,
                observed_versions=(previous, current),
                history_complete=True,
                added_size_bytes=1024,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        subscriptions=subscriptions,
        target_ids=("cn-official-pc",),
    )

    response = await service.subscribe(ClientUpdateRequest(actor=_group_actor()))

    assert response.text == messages.CLIENT_UPDATE_SUBSCRIBED
    assert transport.calls == []
    assert await state.get_baseline(source_id) == baseline

    changes = await service.poll_now()

    assert tuple(change.current for change in changes) == (current,)
    assert transport.calls == [(source_id, previous)]
    pending = await state.pending_events()
    assert len(pending) == 1
    assert tuple(target.origin for target in pending[0].pending_targets) == ("group:1",)


@pytest.mark.asyncio
async def test_initialize_cleans_legacy_platform_metadata_idempotently_and_warns(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "subscriptions.json"
    metadata_by_origin = {
        "group:canonical": "{}",
        "group:pc": '{"platforms":["pc"]}',
        "group:both": '{"platforms":["android","pc","pc"]}',
        "group:ios": '{"platforms":["ios"]}',
        "group:empty": '{"platforms":[]}',
        "group:broken-json": "{",
        "group:not-object": "[]",
        "group:unknown-shape": '{"targets":["cn-official-pc"]}',
    }
    records = [
        {
            "type": messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
            "unified_msg_origin": origin,
            "extra_data": extra_data,
        }
        for origin, extra_data in metadata_by_origin.items()
    ]
    records.extend(
        {
            "type": messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
            "unified_msg_origin": "group:duplicate",
            "extra_data": extra_data,
        }
        for extra_data in (
            "{}",
            '{"platforms":["pc"]}',
            '{"targets":["cn-official-pc"]}',
            '{"platforms":["ios"]}',
        )
    )
    records.append(
        {
            "type": "其他订阅",
            "unified_msg_origin": "group:other",
            "extra_data": '{"platforms":["pc"]}',
        }
    )
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    subscriptions = SubscriptionStore(path)
    service = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "client_updates.json"),
        subscriptions=subscriptions,
    )

    with caplog.at_level("WARNING"):
        await service.initialize()
    first_payload = path.read_text(encoding="utf-8")
    await service.initialize()

    client_subscriptions = tuple(
        (subscription.unified_msg_origin, subscription.extra_data)
        for subscription in await subscriptions.get(
            messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE
        )
    )
    assert client_subscriptions == (
        ("group:canonical", "{}"),
        ("group:pc", "{}"),
        ("group:both", "{}"),
        ("group:ios", '{"platforms":["ios"]}'),
        ("group:empty", '{"platforms":[]}'),
        ("group:broken-json", "{"),
        ("group:not-object", "[]"),
        ("group:unknown-shape", '{"targets":["cn-official-pc"]}'),
        ("group:duplicate", "{}"),
        ("group:duplicate", "{}"),
        ("group:duplicate", '{"targets":["cn-official-pc"]}'),
        ("group:duplicate", '{"platforms":["ios"]}'),
    )
    assert tuple(
        subscription.extra_data for subscription in await subscriptions.get("其他订阅")
    ) == ('{"platforms":["pc"]}',)
    assert path.read_text(encoding="utf-8") == first_payload
    assert "客户端更新订阅元数据无效，跳过清理" in caplog.text


@pytest.mark.asyncio
async def test_same_origin_subscribe_then_unsubscribe_is_serialized(tmp_path) -> None:
    lookup_started = asyncio.Event()
    release_lookup = asyncio.Event()

    class BlockingSubscriptionStore(SubscriptionStore):
        def __init__(self) -> None:
            super().__init__(tmp_path / "subscriptions.json")
            self._blocked_once = False

        async def get(self, sub_type: str, **kwargs: str | None):
            if not self._blocked_once:
                self._blocked_once = True
                lookup_started.set()
                await release_lookup.wait()
            return await super().get(sub_type, **kwargs)

    subscriptions = BlockingSubscriptionStore()
    service = ClientUpdateService(
        ClientUpdateStateStore(tmp_path / "client_updates.json"),
        subscriptions=subscriptions,
    )
    request = ClientUpdateRequest(actor=_group_actor())

    subscribe_task = asyncio.create_task(service.subscribe(request))
    await lookup_started.wait()
    unsubscribe_task = asyncio.create_task(service.unsubscribe(request))
    await asyncio.sleep(0)
    assert not unsubscribe_task.done()

    release_lookup.set()
    subscribe_response, unsubscribe_response = await asyncio.gather(
        subscribe_task,
        unsubscribe_task,
    )

    assert subscribe_response.text == messages.CLIENT_UPDATE_SUBSCRIBED_RETRY
    assert unsubscribe_response.text == messages.CLIENT_UPDATE_UNSUBSCRIBED
    assert await subscriptions.get(messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE) == ()


def _installer_version(source_id: str, revision_id: str) -> ClientSourceVersion:
    """无公开版本号的安装包型 Source 版本（如 B服 PC 安装器）。"""

    return ClientSourceVersion(
        source_id=source_id,
        version_text=None,
        revision_id=revision_id,
        order_key=None,
    )


def _observation(
    current: ClientSourceVersion,
    *,
    history_complete: bool,
    added_size_bytes: int | None,
) -> ClientSourceObservation:
    return ClientSourceObservation(
        current=current,
        observed_versions=(current,),
        history_complete=history_complete,
        added_size_bytes=added_size_bytes,
    )


@pytest.mark.asyncio
async def test_poll_separates_official_and_bilibili_revision_streams() -> None:
    """官服与 B服发行节奏不同：各自 Source 变化只产生自己的 change。"""

    official_source = "cn-official-android-astc-manifest"
    bilibili_source = "cn-bilibili-android-release"
    state = _ReadOnlyState(
        baselines={
            official_source: ClientUpdateBaseline(
                version=_source_version(official_source, "100"),
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            ),
            bilibili_source: ClientUpdateBaseline(
                version=_installer_version(bilibili_source, "installer-a"),
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            ),
        }
    )
    transport = _Transport(
        {
            official_source: _observation(
                _source_version(official_source, "101"),
                history_complete=True,
                added_size_bytes=32,
            ),
            bilibili_source: _observation(
                _installer_version(bilibili_source, "installer-a"),
                history_complete=True,
                added_size_bytes=0,
            ),
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-official-android", "cn-bilibili-android"),
    )

    changes = await service.poll_now()

    assert [change.source_id for change in changes] == [official_source]
    assert changes[0].target_ids == ("cn-official-android",)
    assert {source_id for source_id, _ in transport.calls} == {
        official_source,
        bilibili_source,
    }

    # 第二次轮询：官服稳定、B服安装器变化，只产生 B服 change。
    state.baselines[official_source] = ClientUpdateBaseline(
        version=_source_version(official_source, "101"),
        observed_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    transport.calls.clear()
    transport.observations[official_source] = _observation(
        _source_version(official_source, "101"),
        history_complete=True,
        added_size_bytes=0,
    )
    transport.observations[bilibili_source] = _observation(
        _installer_version(bilibili_source, "installer-b"),
        history_complete=False,
        added_size_bytes=None,
    )

    changes = await service.poll_now()

    assert [change.source_id for change in changes] == [bilibili_source]
    assert changes[0].target_ids == ("cn-bilibili-android",)


@pytest.mark.asyncio
async def test_bilibili_only_config_never_reads_official_source() -> None:
    """只订阅 B服时，官服 Source 不会被读取，官服变化也不会产生推送事件。"""

    bilibili_source = "cn-bilibili-android-release"
    state = _ReadOnlyState(
        baselines={
            bilibili_source: ClientUpdateBaseline(
                version=_installer_version(bilibili_source, "installer-a"),
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            )
        }
    )
    transport = _Transport(
        {
            "cn-official-android-astc-manifest": _observation(
                _source_version("cn-official-android-astc-manifest", "999"),
                history_complete=True,
                added_size_bytes=1024,
            ),
            bilibili_source: _observation(
                _installer_version(bilibili_source, "installer-a"),
                history_complete=True,
                added_size_bytes=0,
            ),
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-bilibili-android",),
    )

    changes = await service.poll_now()

    assert changes == ()
    assert [source_id for source_id, _ in transport.calls] == [bilibili_source]

    transport.observations[bilibili_source] = _observation(
        _installer_version(bilibili_source, "installer-b"),
        history_complete=False,
        added_size_bytes=None,
    )
    state.baselines[bilibili_source] = ClientUpdateBaseline(
        version=_installer_version(bilibili_source, "installer-a"),
        observed_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    changes = await service.poll_now()
    assert [change.target_ids for change in changes] == [("cn-bilibili-android",)]


@pytest.mark.asyncio
async def test_query_reports_opaque_revision_without_version_or_none_text() -> None:
    """无公开版本号的发行渠道：变化可见，消息不显示 None 或伪造版本号。"""

    source_id = "cn-bilibili-pc-release"
    state = _ReadOnlyState(
        baselines={
            source_id: ClientUpdateBaseline(
                version=_installer_version(source_id, "installer-a"),
                observed_at=datetime(2026, 9, 8, tzinfo=UTC),
            )
        }
    )
    transport = _Transport(
        {
            source_id: _observation(
                _installer_version(source_id, "installer-b"),
                history_complete=False,
                added_size_bytes=None,
            )
        }
    )
    service = ClientUpdateService(
        state,
        transport=transport,
        target_ids=("cn-bilibili-pc",),
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

    assert "国服 B服 PC" in response.text
    assert "发行包" in response.text
    assert "None" not in response.text
    assert state.writes == 0
