"""D06：公告目标来源证明与管理边界。"""

from pathlib import Path

import pytest

from src.infrastructure.scheduler_state import SchedulerRegistry
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.admin import AdminApiService, AdminErrorCode
from src.modules.notices import messages
from src.modules.notices.ann_delivery_state import AnnDeliveryStateStore
from src.modules.notices.target_service import (
    AnnouncementTargetService,
    encode_target_id,
)


class Source:
    async def current_announcement_ids(self) -> tuple[str, ...]:
        return ()


@pytest.mark.asyncio
async def test_announcement_service_marks_chat_command_provenance(
    tmp_path: Path,
) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    service = AnnouncementTargetService(
        store, AnnDeliveryStateStore(tmp_path / "delivery.json"), Source()
    )
    result = await service.subscribe(
        origin="platform:group:g1", group_id="g1", bot_id="b1"
    )
    assert result.subscription is not None
    assert result.subscription.provenance == "chat_command"


@pytest.mark.asyncio
async def test_legacy_announcement_target_is_not_dashboard_managed(
    tmp_path: Path,
) -> None:
    store = SubscriptionStore(tmp_path / "subscriptions.json")
    legacy = await store.add(
        messages.ANN_SUBSCRIBE,
        origin="platform:group:legacy",
        group_id="legacy",
        bot_id="b1",
    )
    api = AdminApiService(
        SchedulerRegistry(tmp_path / "scheduler.json"),
        store,
        announcement_target_service=AnnouncementTargetService(
            store, AnnDeliveryStateStore(tmp_path / "delivery.json"), Source()
        ),
    )
    response = await api.disable_target(encode_target_id(legacy))
    assert response.ok is False
    assert response.error is not None
    assert response.error.code is AdminErrorCode.UNSUPPORTED
