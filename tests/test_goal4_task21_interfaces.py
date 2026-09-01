"""Goal 4 / Task 21：公共接口与公告生命周期注入边界。"""

from pathlib import Path

import pytest

from src.infrastructure.http import DnaApiAccountTransport, RequestConcurrencyGate
from src.infrastructure.subscriptions import SubscriptionStore
from src.modules.notices import messages
from tests.test_notices import FakeNoticesTransport
from tests.test_notices_subscriptions import _database_with_binding, _request, _service


def test_http_package_lazy_exports_remain_compatible() -> None:
    assert DnaApiAccountTransport.__name__ == "DnaApiAccountTransport"
    assert RequestConcurrencyGate.__name__ == "RequestConcurrencyGate"


@pytest.mark.asyncio
async def test_announcement_command_requires_lifecycle_service(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    subscriptions = SubscriptionStore(tmp_path / "subscriptions.json")
    service = _service(
        database,
        FakeNoticesTransport(),
        tmp_path,
        subscriptions=subscriptions,
    )

    service.announcement_targets = None
    response = await service.subscribe_ann(_request("订阅公告"))

    assert response.text == messages.NOTICES_SERVICE_UNAVAILABLE
    assert await subscriptions.get(messages.ANN_SUBSCRIBE) == ()
    await database.dispose()
