"""Goal 6 T11：资源同步 service 公开入口与无变化文案 Red 契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.response import PlainTextResponse
from src.infrastructure.resources import ResourceSyncResult
from src.modules.operations.resource_service import ResourceUpdateService


@pytest.mark.asyncio
async def test_sync_resources_service_reports_unchanged_result(tmp_path: Path) -> None:
    service = ResourceUpdateService(
        synchronize=lambda: ResourceSyncResult(
            repository=tmp_path,
            action="unchanged",
            resource_version="v1",
        ),
    )

    response = await service.sync_resources(None)

    assert isinstance(response, PlainTextResponse)
    assert response.text == "资源已是最新，版本 v1"
