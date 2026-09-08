"""Goal 2 / Task 09：成员探测、跨群复核与安全清理契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import (
    AdminApiResponse,
    AdminErrorCode,
    AiocqhttpMembershipProbe,
    DeletionPreview,
    MembershipCapability,
    MembershipProbeResult,
    MembershipService,
    MembershipStatus,
)
from src.modules.notices import messages as notices_messages


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为成员清理测试提供隔离数据库。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


def test_build_runtime_registers_membership_probe_and_service(
    database: AsyncDatabase,
) -> None:
    from src.bootstrap import build_runtime

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=database,
    )

    assert isinstance(runtime.services["membership_probe"], AiocqhttpMembershipProbe)
    assert isinstance(runtime.services["membership_service"], MembershipService)


class FakeRawClient:
    """模拟 aiocqhttp raw client 的动态 action。"""

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def get_group_member_list(self, *, group_id: object) -> object:
        self.calls.append({"group_id": group_id})
        if self.error is not None:
            raise self.error
        return self.response


class FakeMembershipProbe:
    """可注入的三态 probe；支持按调用顺序模拟二次复核变化。"""

    def __init__(
        self,
        statuses: dict[str, MembershipStatus] | list[MembershipStatus] | None = None,
        *,
        capability: MembershipCapability | None = None,
    ) -> None:
        self.statuses = statuses or {}
        self.capability_value = capability or MembershipCapability(
            supported=True,
            platform="aiocqhttp",
        )
        self.calls: list[tuple[str, str]] = []

    def capability(self) -> MembershipCapability:
        return self.capability_value

    async def check(
        self,
        group_id: str,
        user_id: str,
        *,
        bot_id: str | None = None,
    ) -> MembershipProbeResult:
        del bot_id
        self.calls.append((group_id, user_id))
        if isinstance(self.statuses, list):
            status = self.statuses.pop(0)
        else:
            status = self.statuses[group_id]
        return MembershipProbeResult(
            user_id=user_id,
            group_id=group_id,
            status=status,
            platform=self.capability_value.platform,
        )


class FakeDeletionCoordinator:
    """只记录是否越过成员安全门禁。"""

    def __init__(self) -> None:
        self.calls: list[tuple[DeletionPreview, str]] = []

    async def delete_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionPreview]:
        self.calls.append((plan, confirmation_payload))
        return AdminApiResponse.success(plan)


def _platform(name: str, client: object) -> object:
    return SimpleNamespace(
        bot=client,
        meta=lambda: SimpleNamespace(name=name, id="platform-1"),
    )


@pytest.mark.asyncio
async def test_aiocqhttp_probe_uses_raw_group_member_list_and_returns_three_states() -> (
    None
):
    client = FakeRawClient(response=[{"user_id": "user-1", "role": "member"}])
    probe = AiocqhttpMembershipProbe(client)

    present = await probe.check("group-1", "user-1")
    absent = await probe.check("group-1", "user-2")

    assert present.status is MembershipStatus.PRESENT
    assert absent.status is MembershipStatus.ABSENT
    assert client.calls == [{"group_id": "group-1"}, {"group_id": "group-1"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_response,error",
    [
        (None, RuntimeError("network")),
        ({"status": "failed", "retcode": 100}, None),
        ([{"nickname": "missing user id"}], None),
        ({"status": "ok", "data": "not-a-list"}, None),
    ],
)
async def test_aiocqhttp_probe_maps_api_network_and_incomplete_responses_to_unknown(
    raw_response: object,
    error: Exception | None,
) -> None:
    probe = AiocqhttpMembershipProbe(FakeRawClient(raw_response, error))

    result = await probe.check("group-1", "user-1")

    assert result.status is MembershipStatus.UNKNOWN


@pytest.mark.asyncio
async def test_non_aiocqhttp_platform_is_unsupported_and_does_not_call_client() -> None:
    client = FakeRawClient(response=[{"user_id": "user-1"}])
    probe = AiocqhttpMembershipProbe(platform=_platform("discord", client))

    capability = probe.capability()
    result = await probe.check("group-1", "user-1")

    assert capability.supported is False
    assert capability.platform == "discord"
    assert result.status is MembershipStatus.UNKNOWN
    assert result.reason == "unsupported"
    assert client.calls == []


@pytest.mark.asyncio
async def test_raw_client_cannot_override_non_aiocqhttp_platform() -> None:
    client = FakeRawClient(response=[{"user_id": "user-1"}])
    probe = AiocqhttpMembershipProbe(client, platform=_platform("discord", client))

    capability = probe.capability()
    result = await probe.check("group-1", "user-1")

    assert capability.supported is False
    assert capability.platform == "discord"
    assert result.status is MembershipStatus.UNKNOWN
    assert result.reason == "unsupported"
    assert client.calls == []


@pytest.mark.asyncio
async def test_scan_user_collects_binding_and_personal_mh_groups(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-from-binding",
        )
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:personal",
        user_id="user-1",
        uid="user-1",
        group_id="group-from-subscription",
        user_type="group",
    )
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:other-user",
        user_id="user-2",
        uid="user-2",
        group_id="group-not-owned",
        user_type="group",
    )
    probe = FakeMembershipProbe(
        {
            "group-from-binding": MembershipStatus.ABSENT,
            "group-from-subscription": MembershipStatus.PRESENT,
        }
    )

    response = await MembershipService(database, subscriptions, probe).scan_user(
        "user-1"
    )

    assert response.ok is True
    assert response.data is not None
    assert [item.group_id for item in response.data.results] == [
        "group-from-binding",
        "group-from-subscription",
    ]
    assert [item.status for item in response.data.results] == [
        MembershipStatus.ABSENT,
        MembershipStatus.PRESENT,
    ]


@pytest.mark.asyncio
async def test_scan_returns_unsupported_error_for_non_aiocqhttp_capability(
    database: AsyncDatabase,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
        )
    probe = FakeMembershipProbe(
        capability=MembershipCapability(
            supported=False,
            platform="discord",
            reason="unsupported_platform",
        )
    )

    response = await MembershipService(database, None, probe).scan_user("user-1")

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UNSUPPORTED
    assert response.data is not None
    assert response.data.results[0].status is MembershipStatus.UNKNOWN


@pytest.mark.asyncio
async def test_unsupported_capability_disables_scan_without_associated_groups(
    database: AsyncDatabase,
) -> None:
    probe = FakeMembershipProbe(
        capability=MembershipCapability(
            supported=False,
            platform="discord",
            reason="unsupported_platform",
        )
    )

    response = await MembershipService(database, None, probe).scan_user("user-1")

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UNSUPPORTED


@pytest.mark.asyncio
async def test_single_group_cleanup_deletes_only_exact_personal_mh_subscription(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:one",
        user_id="user-1",
        uid="user-1",
        group_id="group-1",
        user_type="group",
    )
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:two",
        user_id="user-1",
        uid="user-1",
        group_id="group-2",
        user_type="group",
    )
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:other-user",
        user_id="user-2",
        uid="user-2",
        group_id="group-1",
        user_type="group",
    )
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="direct:user-1",
        user_id="user-1",
        uid="user-1",
        user_type="direct",
    )
    await subscriptions.add(
        notices_messages.ANN_SUBSCRIBE,
        origin="group:one-announcement",
        user_id="user-1",
        group_id="group-1",
        user_type="group",
    )
    probe = FakeMembershipProbe({"group-1": MembershipStatus.ABSENT})

    response = await MembershipService(database, subscriptions, probe).cleanup_group(
        "user-1",
        "group-1",
    )

    assert response.ok is True
    assert response.data is not None
    assert response.data.deleted_count == 1
    remaining = await subscriptions.list_all()
    assert not any(
        sub.type == notices_messages.MH_SUBSCRIBE
        and sub.user_id == "user-1"
        and sub.group_id == "group-1"
        for sub in remaining
    )
    assert any(sub.unified_msg_origin == "group:two" for sub in remaining)
    assert any(sub.unified_msg_origin == "direct:user-1" for sub in remaining)
    assert any(sub.type == notices_messages.ANN_SUBSCRIBE for sub in remaining)
    assert any(sub.user_id == "user-2" for sub in remaining)


@pytest.mark.asyncio
async def test_single_group_cleanup_never_deletes_when_membership_is_not_absent(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:one",
        user_id="user-1",
        uid="user-1",
        group_id="group-1",
        user_type="group",
    )
    probe = FakeMembershipProbe(
        [MembershipStatus.PRESENT, MembershipStatus.UNKNOWN],
    )
    service = MembershipService(database, subscriptions, probe)

    present = await service.cleanup_group("user-1", "group-1")
    unknown = await service.cleanup_group("user-1", "group-1")

    assert present.ok is False
    assert present.data is not None
    assert present.data.deleted_count == 0
    assert unknown.ok is False
    assert unknown.error is not None
    assert unknown.error.code is AdminErrorCode.UPSTREAM
    assert len(await subscriptions.list_all()) == 1


@pytest.mark.asyncio
async def test_global_delete_blocks_unknown_or_unsupported_without_calling_coordinator(
    database: AsyncDatabase,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
        )
    probe = FakeMembershipProbe({"group-1": MembershipStatus.UNKNOWN})
    coordinator = FakeDeletionCoordinator()
    service = MembershipService(database, None, probe, coordinator)
    plan = DeletionPreview(
        user_id="user-1",
        uid=None,
        affected_uids=("1001",),
        delete_resources=("account_bindings",),
        preserve_resources=(),
        confirmation_payload="delete:user:user-1",
    )

    response = await service.delete_user(plan, plan.confirmation_payload)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UPSTREAM
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_global_delete_rejects_duplicate_uids_before_membership_probe(
    database: AsyncDatabase,
) -> None:
    probe = FakeMembershipProbe({})
    coordinator = FakeDeletionCoordinator()
    service = MembershipService(database, None, probe, coordinator)
    plan = DeletionPreview(
        user_id="user-1",
        uid=None,
        affected_uids=("1001", "1001"),
        delete_resources=("account_bindings",),
        preserve_resources=(),
        confirmation_payload="delete:user:user-1",
    )

    response = await service.delete_user(plan, plan.confirmation_payload)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.VALIDATION
    assert probe.calls == []
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_global_delete_rescans_before_delegating_and_rejects_stale_absent_result(
    database: AsyncDatabase,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
        )
    probe = FakeMembershipProbe(
        [MembershipStatus.ABSENT, MembershipStatus.PRESENT],
    )
    coordinator = FakeDeletionCoordinator()
    service = MembershipService(database, None, probe, coordinator)
    plan = DeletionPreview(
        user_id="user-1",
        uid=None,
        affected_uids=("1001",),
        delete_resources=("account_bindings",),
        preserve_resources=(),
        confirmation_payload="delete:user:user-1",
    )

    initial = await service.scan_user("user-1")
    response = await service.delete_user(
        plan, plan.confirmation_payload, scan=initial.data
    )

    assert initial.ok is True
    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.CONFLICT
    assert coordinator.calls == []
    assert probe.calls == [("group-1", "user-1"), ("group-1", "user-1")]


@pytest.mark.asyncio
async def test_global_delete_delegates_only_after_all_groups_are_absent(
    database: AsyncDatabase,
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
        )
    probe = FakeMembershipProbe({"group-1": MembershipStatus.ABSENT})
    coordinator = FakeDeletionCoordinator()
    service = MembershipService(database, None, probe, coordinator)
    plan = DeletionPreview(
        user_id="user-1",
        uid=None,
        affected_uids=("1001",),
        delete_resources=("account_bindings",),
        preserve_resources=(),
        confirmation_payload="delete:user:user-1",
    )

    response = await service.delete_user(plan, plan.confirmation_payload)

    assert response.ok is True
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0][0] == plan
