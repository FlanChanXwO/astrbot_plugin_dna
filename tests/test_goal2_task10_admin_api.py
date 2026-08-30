"""Goal 2 / Task 10：任务、投递目标与成员管理 API 契约。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.infrastructure.notices_scheduler import NoticesScheduler
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.scheduler_state import SchedulerRegistry
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import (
    AdminApiResponse,
    AdminApiService,
    AdminError,
    AdminErrorCode,
    TaskTargetUpdate,
)
from src.modules.notices import messages as notices_messages

TZ = ZoneInfo("Asia/Shanghai")


class _Checkin:
    async def auto_sign_all(self) -> str:
        return "ok"

    async def clear_sign_records_before(self, record_date) -> int:
        del record_date
        return 0


class _Notices:
    async def push_mh_now(self) -> int:
        return 0

    async def poll_ann_now(self) -> int:
        return 0


class _MembershipApi:
    def __init__(self) -> None:
        self.scan_response = AdminApiResponse.failure(
            AdminError(AdminErrorCode.UNSUPPORTED, "当前平台不支持群成员探测")
        )
        self.cleanup_response = AdminApiResponse.failure(
            AdminError(AdminErrorCode.PARTIAL, "群清理部分完成，可重试")
        )
        self.delete_response = AdminApiResponse.failure(
            AdminError(AdminErrorCode.UPSTREAM, "无法确认用户群成员状态")
        )

    async def scan_user(self, user_id: str):
        del user_id
        return self.scan_response

    async def cleanup_group(self, user_id: str, group_id: str):
        del user_id, group_id
        return self.cleanup_response

    async def delete_user(self, plan, confirmation_payload: str, *, scan=None):
        del plan, confirmation_payload, scan
        return self.delete_response


@pytest.fixture
def admin_api(
    tmp_path: Path,
) -> tuple[AdminApiService, dict[str, object], SubscriptionStore]:
    registry = SchedulerRegistry(tmp_path / "scheduler_state.json")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    sign_scheduler = SignScheduler(
        _Checkin(),
        subscriptions,
        sign_time="00:05",
        scheduled_enabled=True,
        enable_all_users=True,
        registry=registry,
    )
    notices_scheduler = NoticesScheduler(
        _Notices(),
        poll_minutes=10,
        registry=registry,
    )
    config: dict[str, object] = {
        "sign_in": {"sign_time": "00:05"},
        "notifications": {
            "announcement_check_minutes": 10,
        },
    }
    api = AdminApiService(
        registry,
        subscriptions,
        {
            "dnaby_sign_daily": sign_scheduler,
            "dnaby_sign_cleanup": sign_scheduler,
            "dnaby_mh_push": notices_scheduler,
            "dnaby_ann_poll": notices_scheduler,
        },
        _MembershipApi(),
        config_store=config,
    )
    return api, config, subscriptions


@pytest.mark.asyncio
async def test_task_api_lists_allowlisted_snapshots_and_has_no_create_or_restore(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, _config, _subscriptions = admin_api

    response = await api.list_tasks()

    assert response.ok is True
    assert response.data is not None
    assert {task.id for task in response.data} == {
        "dnaby_sign_daily",
        "dnaby_sign_cleanup",
        "dnaby_mh_push",
        "dnaby_ann_poll",
    }
    assert not hasattr(api, "create_task")
    assert not hasattr(api, "restore_task")


@pytest.mark.asyncio
async def test_task_api_validates_schedule_updates_and_preserves_tombstone_boundary(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, config, _subscriptions = admin_api

    updated = await api.update_task("dnaby_sign_daily", schedule="daily@23:07")
    assert updated.ok is True
    assert updated.data is not None
    assert updated.data.schedule == "daily@23:07"
    assert config["sign_in"]["sign_time"] == "23:07"  # type: ignore[index]

    invalid = await api.update_task("dnaby_sign_daily", schedule="daily@25:00")
    assert invalid.ok is False
    assert invalid.error is not None
    assert invalid.error.code is AdminErrorCode.VALIDATION

    unknown = await api.update_task("user-provided-task", schedule="daily@01:00")
    assert unknown.ok is False
    assert unknown.error is not None
    assert unknown.error.code is AdminErrorCode.NOT_FOUND

    mh_updated = await api.update_task("dnaby_mh_push", schedule="hourly@07:08")
    assert mh_updated.ok is False
    assert mh_updated.error is not None
    assert mh_updated.error.code is AdminErrorCode.CONFLICT
    assert "secret_push_time" not in config["notifications"]  # type: ignore[operator]

    ann_updated = await api.update_task("dnaby_ann_poll", schedule="interval@20m")
    assert ann_updated.ok is True
    assert ann_updated.data is not None
    assert ann_updated.data.schedule == "interval@20m"
    assert config["notifications"]["announcement_check_minutes"] == 20  # type: ignore[index]

    invalid_interval = await api.update_task("dnaby_ann_poll", schedule="interval@0m")
    assert invalid_interval.ok is False
    assert invalid_interval.error is not None
    assert invalid_interval.error.code is AdminErrorCode.VALIDATION

    paused = await api.pause_task("dnaby_sign_daily")
    assert paused.ok is True
    assert paused.data is not None and paused.data.state.value == "paused"
    resumed = await api.resume_task("dnaby_sign_daily")
    assert resumed.ok is True
    assert resumed.data is not None and resumed.data.state.value == "running"

    maintenance_delete = await api.delete_task("dnaby_sign_cleanup")
    assert maintenance_delete.ok is False
    assert maintenance_delete.error is not None
    assert maintenance_delete.error.code is AdminErrorCode.CONFLICT

    deleted = await api.delete_task("dnaby_sign_daily")
    assert deleted.ok is True
    assert (await api.get_task("dnaby_sign_daily")).error is not None

    cannot_restore = await api.resume_task("dnaby_sign_daily")
    assert cannot_restore.ok is False
    assert cannot_restore.error is not None
    assert cannot_restore.error.code is AdminErrorCode.CONFLICT


def test_build_runtime_wires_framework_agnostic_admin_api_service(
    tmp_path: Path,
) -> None:
    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    assert isinstance(runtime.services["admin_api_service"], AdminApiService)


@pytest.mark.asyncio
async def test_running_schedule_update_rebuilds_the_affected_loop(
    tmp_path: Path,
) -> None:
    registry = SchedulerRegistry(tmp_path / "scheduler_state.json")
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")

    async def sleep(_seconds: float) -> None:
        await asyncio.Future()

    scheduler = SignScheduler(
        _Checkin(),
        subscriptions,
        sign_time="00:05",
        scheduled_enabled=True,
        enable_all_users=True,
        now=lambda: datetime(2026, 8, 28, 23, 59, tzinfo=TZ),
        sleep=sleep,
        registry=registry,
    )

    await scheduler.start()
    await asyncio.sleep(0)
    old_task = scheduler._task_by_id["dnaby_sign_daily"]

    await scheduler.update_task("dnaby_sign_daily", "daily@23:07")
    await asyncio.sleep(0)

    new_task = scheduler._task_by_id["dnaby_sign_daily"]
    snapshot = await registry.get_snapshot("dnaby_sign_daily")
    assert new_task is not old_task
    assert old_task.done() is True
    assert snapshot is not None
    assert snapshot.next_run_at is not None
    assert snapshot.next_run_at.hour == 23
    assert snapshot.next_run_at.minute == 7

    await scheduler.stop()


@pytest.mark.asyncio
async def test_schedule_config_save_failure_rolls_back_scheduler_and_config(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, config, _subscriptions = admin_api

    async def fail_save() -> None:
        raise OSError("config is read-only")

    api._save_config = fail_save
    response = await api.update_task("dnaby_sign_daily", schedule="daily@23:07")

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.INTERNAL
    assert config["sign_in"]["sign_time"] == "00:05"  # type: ignore[index]
    current = await api.get_task("dnaby_sign_daily")
    assert current.data is not None
    assert current.data.schedule == "daily@00:05"


@pytest.mark.asyncio
async def test_target_api_updates_and_deletes_existing_subscription_only(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, _config, subscriptions = admin_api
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:one",
        user_id="user-1",
        uid="user-1",
        group_id="group-1",
        bot_id="bot-1",
        extra_message="角色:拆解",
    )
    await subscriptions.add(
        notices_messages.ANN_SUBSCRIBE,
        origin="group:ann",
        user_id="user-2",
        group_id="group-2",
    )

    mh_targets = await api.list_targets("dnaby_mh_push")
    assert mh_targets.ok is True
    assert mh_targets.data is not None
    assert len(mh_targets.data) == 1
    target = mh_targets.data[0]
    assert target.to_dict()["unified_msg_origin"] == "group:one"

    updated = await api.update_target(
        target.id,
        TaskTargetUpdate(bot_id="bot-2", extra_message="角色:追缉"),
    )
    assert updated.ok is True
    assert updated.data is not None
    assert updated.data.bot_id == "bot-2"
    assert updated.data.id == target.id

    stored = await subscriptions.get(notices_messages.MH_SUBSCRIBE)
    assert stored[0].bot_id == "bot-2"
    assert stored[0].extra_message == "角色:追缉"

    deleted = await api.delete_target(target.id)
    assert deleted.ok is True
    assert deleted.data is not None
    assert await subscriptions.get(notices_messages.MH_SUBSCRIBE) == ()
    assert len(await subscriptions.get(notices_messages.ANN_SUBSCRIBE)) == 1

    malformed = await api.delete_target("not-a-target-id")
    assert malformed.ok is False
    assert malformed.error is not None
    assert malformed.error.code is AdminErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_target_api_surfaces_store_failure_without_reporting_success(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, _config, subscriptions = admin_api
    await subscriptions.add(
        notices_messages.MH_SUBSCRIBE,
        origin="group:one",
        user_id="user-1",
        uid="user-1",
        group_id="group-1",
    )
    target = (await api.list_targets("dnaby_mh_push")).data[0]  # type: ignore[index]

    def fail_save() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(subscriptions, "_save_unlocked", fail_save)
    response = await api.update_target(target.id, TaskTargetUpdate(group_id="group-2"))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.INTERNAL
    assert (await subscriptions.get(notices_messages.MH_SUBSCRIBE))[
        0
    ].group_id == "group-1"


@pytest.mark.asyncio
async def test_member_api_preserves_unsupported_partial_and_upstream_error_contract(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, _config, _subscriptions = admin_api

    scan = await api.scan_members("user-1")
    cleanup = await api.cleanup_member_group("user-1", "group-1")
    deletion = await api.delete_member_user(object(), "confirmation")

    assert scan.error is not None and scan.error.code is AdminErrorCode.UNSUPPORTED
    assert cleanup.error is not None and cleanup.error.code is AdminErrorCode.PARTIAL
    assert deletion.error is not None and deletion.error.code is AdminErrorCode.UPSTREAM


@pytest.mark.asyncio
async def test_member_api_maps_unexpected_probe_failure_to_upstream(
    admin_api: tuple[AdminApiService, dict[str, object], SubscriptionStore],
) -> None:
    api, _config, _subscriptions = admin_api

    async def fail_scan(user_id: str):
        del user_id
        raise RuntimeError("private upstream detail")

    api.membership_service.scan_user = fail_scan  # type: ignore[method-assign]
    response = await api.scan_members("user-1")

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UPSTREAM
    assert "private upstream detail" not in response.error.message
