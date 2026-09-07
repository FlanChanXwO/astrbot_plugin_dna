"""T25：资源状态字段、轻量边界与同步结果持久化契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.infrastructure.resources import (
    ResourceGenerationValidator,
    ResourceSnapshotCoordinator,
    ResourceSyncError,
    ResourceSyncResult,
)
from src.infrastructure.resources import generation as generation_module
from src.modules.operations.resource_service import ResourceUpdateService

GENERATION = "a" * 40


class _ForbiddenRunner:
    def __call__(
        self,
        args: tuple[str, ...],
        cwd: Path | None = None,
    ) -> Any:
        del args, cwd
        raise AssertionError("资源状态不得调用 Git")


def _coordinator(tmp_path: Path) -> ResourceSnapshotCoordinator:
    return ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=_ForbiddenRunner(),
        validator=ResourceGenerationValidator(),
    )


def _write_active_generation(
    coordinator: ResourceSnapshotCoordinator,
    *,
    manifest: str | None = None,
) -> Path:
    root = coordinator.generations_root / GENERATION
    (root / "fonts").mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (root / "resource_manifest.json").write_text(manifest, encoding="utf-8")
    coordinator.generations_root.mkdir(parents=True, exist_ok=True)
    coordinator.state_path.write_text(
        json.dumps({"generation": GENERATION}) + "\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.asyncio
async def test_resource_status_exposes_active_metadata_without_heavy_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """状态命令展示五项运行期元数据，但不得加载、校验或解码资源。"""

    coordinator = _coordinator(tmp_path)
    _write_active_generation(
        coordinator,
        manifest=json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "status-v1",
            }
        ),
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("资源状态不得触发完整资源操作")

    monkeypatch.setattr(coordinator, "load_current", forbidden)
    monkeypatch.setattr(ResourceGenerationValidator, "validate", forbidden)
    monkeypatch.setattr(generation_module, "_content_sha256", forbidden)
    monkeypatch.setattr(generation_module.Image, "open", forbidden)

    response = await ResourceUpdateService(
        synchronize=lambda: (_ for _ in ()).throw(
            AssertionError("资源状态不得触发同步")
        ),
        resource_root=tmp_path / "legacy-resources",
        resource_snapshots=coordinator,
    ).status()

    assert f"repository path: {coordinator.repository}" in response.text
    assert f"generation id: {GENERATION}" in response.text
    assert f"active pointer: {coordinator.state_path}" in response.text
    assert "resource_version: status-v1" in response.text
    assert "last sync result: 未记录" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("manifest", [None, "{"], ids=["missing", "corrupt"])
async def test_resource_status_reports_no_current_or_bad_manifest_explicitly(
    tmp_path: Path,
    manifest: str | None,
) -> None:
    """无 current、manifest 缺失和损坏都必须显式呈现，不能伪造成正常版本。"""

    coordinator = _coordinator(tmp_path)
    if manifest is None:
        coordinator.repository.mkdir(parents=True)
    else:
        _write_active_generation(coordinator, manifest=manifest)

    response = await ResourceUpdateService(
        synchronize=lambda: (_ for _ in ()).throw(
            AssertionError("资源状态不得触发同步")
        ),
        resource_snapshots=coordinator,
    ).status()

    if manifest is None:
        assert "generation id: 未发布" in response.text
        assert "resource_version: 未发布" in response.text
        assert "manifest: 缺失" in response.text
    else:
        assert f"generation id: {GENERATION}" in response.text
        assert "resource_version: 未知" in response.text
        assert "manifest: 损坏或不可读" in response.text


@pytest.mark.asyncio
async def test_resource_status_reports_missing_manifest_when_repository_absent(
    tmp_path: Path,
) -> None:
    """仓库尚不存在时仍明确报告 manifest 缺失和未发布状态。"""

    coordinator = _coordinator(tmp_path)
    response = await ResourceUpdateService(
        synchronize=lambda: (_ for _ in ()).throw(
            AssertionError("资源状态不得触发同步")
        ),
        resource_snapshots=coordinator,
    ).status()

    assert "generation id: 未发布" in response.text
    assert "resource_version: 未发布" in response.text
    assert "manifest: 缺失" in response.text
    assert "公共资源仓库尚未同步到数据目录" in response.text


@pytest.mark.asyncio
async def test_resource_status_reports_invalid_utf8_manifest_explicitly(
    tmp_path: Path,
) -> None:
    """非法 UTF-8 manifest 也必须归类为不可读，而不是让状态命令崩溃。"""

    coordinator = _coordinator(tmp_path)
    root = _write_active_generation(coordinator)
    (root / "resource_manifest.json").write_bytes(b"\xff")

    response = await ResourceUpdateService(
        synchronize=lambda: (_ for _ in ()).throw(
            AssertionError("资源状态不得触发同步")
        ),
        resource_snapshots=coordinator,
    ).status()

    assert "manifest: 损坏或不可读" in response.text


@pytest.mark.asyncio
async def test_sync_result_is_safe_and_persistent_across_reload_without_overwriting_current(
    tmp_path: Path,
) -> None:
    """成功/失败摘要跨重载可读，失败不会覆盖原 active generation。"""

    coordinator = _coordinator(tmp_path)
    _write_active_generation(
        coordinator,
        manifest=json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "status-v1",
            }
        ),
    )
    pointer_before = coordinator.state_path.read_bytes()
    success = ResourceSyncResult(
        repository=coordinator.repository,
        action="updated",
        resource_version="status-v2",
        commit_sha="b" * 40,
    )

    def successful_sync() -> ResourceSyncResult:
        # 真实 bootstrap 将 coordinator.synchronize 作为 canonical owner。
        coordinator.record_sync_result(success)
        return success

    success_response = await ResourceUpdateService(
        synchronize=successful_sync,
        resource_snapshots=coordinator,
    ).sync_resources(None)
    assert "资源已更新完成，版本 status-v2" in success_response.text

    reloaded = _coordinator(tmp_path)
    success_status = await ResourceUpdateService(
        synchronize=lambda: success,
        resource_snapshots=reloaded,
    ).status()
    assert "last sync result: 成功" in success_status.text
    assert "status-v2" in success_status.text
    assert "b" * 40 in success_status.text

    secret = "Bearer super-secret"

    def fail() -> ResourceSyncResult:
        error = ResourceSyncError(secret)
        # 真实 coordinator 在同步边界记录失败，service 只负责响应映射。
        coordinator.record_sync_failure(error)
        raise error

    failure_response = await ResourceUpdateService(
        synchronize=fail,
        resource_snapshots=coordinator,
    ).sync_resources(None)
    assert "资源同步失败" in failure_response.text
    assert coordinator.state_path.read_bytes() == pointer_before

    persisted = json.loads(
        coordinator.last_sync_path.read_text(encoding="utf-8"),
    )
    assert persisted["status"] == "failed"
    assert persisted["error_type"] == "ResourceSyncError"
    assert secret not in coordinator.last_sync_path.read_text(encoding="utf-8")

    failed_status = await ResourceUpdateService(
        synchronize=fail,
        resource_snapshots=_coordinator(tmp_path),
    ).status()
    assert "last sync result: 失败" in failed_status.text
    assert "ResourceSyncError" in failed_status.text
    assert secret not in failed_status.text
