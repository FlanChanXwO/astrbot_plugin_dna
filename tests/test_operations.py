"""公共资源状态命令的离线契约。

自定义面板图管理已经移除；这里仅覆盖仍然保留的资源状态读取边界。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.entry.response import PlainTextResponse
from src.modules.operations import messages
from src.modules.operations.resource_service import ResourceUpdateService


def _service(
    tmp_path: Path,
    *,
    resource_root: Path | None = None,
    resource_snapshots: object | None = None,
) -> ResourceUpdateService:
    return ResourceUpdateService(
        synchronize=lambda: None,  # status 查询不会触发同步
        resource_root=resource_root or tmp_path / "resources",
        resource_snapshots=resource_snapshots,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_resource_status_reports_manifest_state(tmp_path: Path) -> None:
    """资源状态展示 manifest 与目录信息。"""

    service = _service(tmp_path)
    empty = await service.status()
    assert isinstance(empty, PlainTextResponse)
    assert messages.RESOURCE_STATUS_EMPTY in empty.text

    resource_root = tmp_path / "resources"
    resource_root.mkdir(parents=True)
    (resource_root / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts", "panel"],
                "resource_version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    (resource_root / "fonts").mkdir()
    with_status = await _service(tmp_path, resource_root=resource_root).status()
    assert "manifest: v1" in with_status.text
    assert "必需目录: 1/2 存在" in with_status.text


@pytest.mark.asyncio
async def test_resource_status_uses_a_generation_lease(tmp_path: Path) -> None:
    """资源状态读取期间固定同一个 generation，避免热刷新切换根目录。"""

    generation_root = tmp_path / "resource_generations" / ("a" * 40)
    (generation_root / "fonts").mkdir(parents=True)
    (generation_root / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "v1",
            }
        ),
        encoding="utf-8",
    )

    class Snapshot:
        root = generation_root

    class LeaseProbe:
        entered = False
        exited = False

        def optional_lease(self):
            return self

        def __enter__(self):
            self.entered = True
            return Snapshot()

        def __exit__(self, _exc_type, _exc_value, _traceback):
            self.exited = True

    lease_probe = LeaseProbe()
    response = await _service(
        tmp_path,
        resource_root=tmp_path / "legacy-resources",
        resource_snapshots=lease_probe,
    ).status()

    assert isinstance(response, PlainTextResponse)
    assert str(generation_root) in response.text
    assert lease_probe.entered
    assert lease_probe.exited
