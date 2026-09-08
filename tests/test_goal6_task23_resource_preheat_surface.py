"""T23：移除资源启动预热，但保留资源同步的生命周期排空面。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.response import PlainTextResponse
from src.infrastructure.resources import ResourceSyncResult
from src.modules.operations.resource_service import ResourceUpdateService


ROOT = Path(__file__).resolve().parents[1]
LOADER_SCRIPT = ROOT / "scripts" / "ci" / "check_astrbot_plugin_load.py"


def test_resource_service_drops_preheat_but_keeps_shutdown_surface() -> None:
    """资源服务不再暴露启动预热，但仍保留终止时排空入口。"""

    assert not hasattr(ResourceUpdateService, "start_preheat")
    assert not hasattr(ResourceUpdateService, "preheat_error")
    assert hasattr(ResourceUpdateService, "stop")


def test_loader_harness_drops_preheat_guard() -> None:
    """loader harness 不应再通过 monkeypatch 隔离已经删除的预热入口。"""

    loader_source = LOADER_SCRIPT.read_text(encoding="utf-8")

    assert "_ResourcePreheatGuard" not in loader_source
    assert "start_preheat" not in loader_source


@pytest.mark.asyncio
async def test_explicit_resource_sync_remains_available(tmp_path: Path) -> None:
    """删除启动预热后，显式同步仍执行并返回真实结果文案。"""

    calls: list[str] = []

    def synchronize() -> ResourceSyncResult:
        calls.append("sync")
        return ResourceSyncResult(
            repository=tmp_path,
            action="updated",
            resource_version="2.0",
        )

    service = ResourceUpdateService(synchronize=synchronize, resource_root=tmp_path)
    response = await service.sync_resources(None)

    assert calls == ["sync"]
    assert isinstance(response, PlainTextResponse)
    assert "资源已更新完成，版本 2.0" in response.text
