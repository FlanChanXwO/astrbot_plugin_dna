"""Goal 1 O08：资源服务与管理员下载的生命周期契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.bootstrap import build_runtime
from src.infrastructure.persistence import AsyncDatabase


@pytest.mark.asyncio
async def test_bootstrap_preserves_injected_resource_service_and_drains_on_terminate(
    tmp_path: Path,
) -> None:
    """runtime 保留注入的资源服务，并在终止时排空其后台同步。"""

    class _ResourceServiceSpy:
        def __init__(self) -> None:
            self.stop_calls = 0

        async def stop(self) -> None:
            self.stop_calls += 1

    resource_service = _ResourceServiceSpy()
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {"login": {"port": 0}},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
        services={"resource_update_service": resource_service},
    )

    await runtime.initialize()
    await runtime.terminate()

    assert runtime.services["resource_update_service"] is resource_service
    assert resource_service.stop_calls == 1
