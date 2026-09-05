"""Goal 1 O08：资源预热与管理员下载的生命周期契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.bootstrap import build_runtime
from src.infrastructure.persistence import AsyncDatabase


class FakeResourceUpdateService:
    """只记录生命周期调用，避免 bootstrap 契约测试访问真实资源仓库。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_preheat(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


@pytest.mark.asyncio
async def test_bootstrap_does_not_preheat_injected_resource_service(
    tmp_path: Path,
) -> None:
    """runtime 启停不应自动触发资源同步，资源服务仍可注入供管理命令使用。"""

    resource_service = FakeResourceUpdateService()
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {"login": {"port": 0}},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
        services={"resource_update_service": resource_service},
    )

    await runtime.initialize()
    await runtime.terminate()

    assert runtime.services["resource_update_service"] is resource_service
    assert resource_service.calls == []
