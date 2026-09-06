"""Goal 4 / Task 18：Admin API 公告目标生命周期契约。"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from src.entry.admin_web import ADMIN_WEB_PREFIX, build_admin_web_routes
from src.infrastructure.scheduler_state import SchedulerRegistry
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import AdminApiService, AdminErrorCode, TaskTargetUpdate
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.target_service import (
    AnnouncementTargetService,
    encode_target_id,
)


class Source:
    async def current_announcement_ids(self) -> tuple[str, ...]:
        return ("1",)


@pytest_asyncio.fixture
async def admin(tmp_path: Path):
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    targets = AnnouncementTargetService(
        subscriptions,
        AnnDeliveryStateStore(tmp_path / "ann_delivery_state.json"),
        Source(),
    )
    api = AdminApiService(
        SchedulerRegistry(tmp_path / "scheduler.json"),
        subscriptions,
        announcement_target_service=targets,
    )
    created = await targets.subscribe(
        origin="platform:group:g1", group_id="g1", bot_id="b1"
    )
    assert created.subscription is not None
    target_id = encode_target_id(created.subscription)
    return api, target_id, subscriptions


@pytest.mark.asyncio
async def test_admin_enable_disable_delete_use_announcement_target_service(
    admin,
) -> None:
    api, target_id, subscriptions = admin

    disabled = await api.disable_target(target_id)
    assert disabled.ok is True
    assert disabled.data is not None and disabled.data.enabled is False

    enabled = await api.enable_target(target_id)
    assert enabled.ok is True
    assert enabled.data is not None and enabled.data.enabled is True

    deleted = await api.delete_target(target_id)
    assert deleted.ok is True
    assert await subscriptions.list_all() == ()


@pytest.mark.asyncio
async def test_admin_rejects_identity_updates_for_announcement_target(admin) -> None:
    api, target_id, _subscriptions = admin

    response = await api.update_target(target_id, TaskTargetUpdate(group_id="other"))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UNSUPPORTED


def test_admin_routes_expose_target_lifecycle_actions() -> None:
    paths = {route.path for route in build_admin_web_routes({})}
    assert f"{ADMIN_WEB_PREFIX}/targets/<target_id>/enable" in paths
    assert f"{ADMIN_WEB_PREFIX}/targets/<target_id>/disable" in paths
