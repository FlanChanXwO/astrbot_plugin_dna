"""公共资源同步核心回归测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event, Lock

import pytest

from src.entry.response import PlainTextResponse
from src.infrastructure.rendering.player import ResourceMap
from src.infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
    ResourceSyncError,
    ResourceSyncResult,
)
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.manifest import (
    ResourceManifest,
    ResourceManifestError,
)
from src.modules.operations.resource_service import ResourceUpdateService


def _service(tmp_path: Path, *, synchronize=None) -> ResourceUpdateService:
    return ResourceUpdateService(
        synchronize=synchronize
        or (
            lambda: ResourceSyncResult(
                repository=tmp_path / "r", action="cloned", resource_version="1.0"
            )
        ),
    )


@pytest.mark.asyncio
async def test_sync_resources_reports_clone_and_update(tmp_path: Path) -> None:
    """下载成功区分克隆与更新动作并报告版本。"""

    cloned = _service(
        tmp_path,
        synchronize=lambda: ResourceSyncResult(
            repository=tmp_path, action="cloned", resource_version="1.0"
        ),
    )
    updated = _service(
        tmp_path,
        synchronize=lambda: ResourceSyncResult(
            repository=tmp_path, action="updated", resource_version="2.0"
        ),
    )

    clone_resp = await cloned.sync_resources(None)
    update_resp = await updated.sync_resources(None)

    assert isinstance(clone_resp, PlainTextResponse)
    assert "资源已克隆完成，版本 1.0" in clone_resp.text
    assert "资源已更新完成，版本 2.0" in update_resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GitUnavailableError(), "未找到 git 可执行文件"),
        (ResourceRemoteMismatchError(), "origin 与配置的资源仓库不一致"),
        (ResourceLocalChangesError("M panel/101.png"), "存在本地修改"),
        (ResourceSyncError("sync exploded"), "资源同步失败：sync exploded"),
    ],
)
async def test_sync_resources_failures_are_visible(
    tmp_path: Path, error: Exception, expected: str
) -> None:
    """Git 缺失/远端不匹配/本地修改/同步失败均返回可见文案，不自动覆盖。"""

    def boom() -> ResourceSyncResult:
        raise error

    service = _service(tmp_path, synchronize=boom)
    response = await service.sync_resources(None)

    assert isinstance(response, PlainTextResponse)
    assert expected in response.text


@pytest.mark.asyncio
async def test_concurrent_sync_resources_uses_one_single_flight(tmp_path: Path) -> None:
    """并发管理员请求必须等待同一次同步，而不是重复执行 Git。"""

    started = Event()
    release = Event()
    calls = 0
    calls_lock = Lock()

    def synchronize() -> ResourceSyncResult:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait()
        return ResourceSyncResult(
            repository=tmp_path,
            action="updated",
            resource_version="2.0",
        )

    service = _service(tmp_path, synchronize=synchronize)
    first = asyncio.create_task(service.sync_resources(None))
    await asyncio.to_thread(started.wait)
    second = asyncio.create_task(service.sync_resources(None))
    await asyncio.sleep(0)
    release.set()

    responses = await asyncio.gather(first, second)

    assert calls == 1
    assert all(isinstance(response, PlainTextResponse) for response in responses)


@pytest.mark.asyncio
async def test_stop_drains_inflight_sync_and_rejects_new_work(tmp_path: Path) -> None:
    """插件终止时必须排空线程同步，并阻止新的同步任务进入。"""

    started = Event()
    release = Event()
    calls = 0

    def synchronize() -> ResourceSyncResult:
        nonlocal calls
        calls += 1
        started.set()
        release.wait()
        return ResourceSyncResult(
            repository=tmp_path,
            action="updated",
            resource_version="2.0",
        )

    service = _service(tmp_path, synchronize=synchronize)
    sync_task = asyncio.create_task(service.synchronize_once())
    await asyncio.to_thread(started.wait)

    try:
        stop_task = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()

        release.set()
        result = await sync_task
        await stop_task
    finally:
        release.set()
        if not sync_task.done():
            await sync_task

    assert result.action == "updated"
    assert calls == 1
    with pytest.raises(ResourceSyncError, match="资源同步服务正在停止"):
        await service.synchronize_once()


def test_restore_current_trusts_published_pointer_without_full_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """插件重载只能快速恢复已发布 generation，不得重新执行完整 validator。"""

    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "repository",
        generations_root=tmp_path / "generations",
    )
    content_sha256 = "a" * 64
    light_snapshot = ResourceSnapshot(
        commit_sha="abc123",
        root=tmp_path / "generations" / "abc123",
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("fonts",),
            resource_version="5",
        ),
        player_resources=ResourceMap(),
        encyclopedia_resources=EncyclopediaResourceStore(),
    )
    monkeypatch.setattr(
        coordinator,
        "_read_generation_pointer",
        lambda: ("abc123", content_sha256),
    )
    monkeypatch.setattr(
        coordinator,
        "_load_light_snapshot",
        lambda _generation: light_snapshot,
    )

    def fail_if_validated() -> None:
        raise AssertionError("reload must not execute full resource validation")

    monkeypatch.setattr(coordinator, "validate_current", fail_if_validated)

    restored = coordinator.restore_current()

    assert restored is not None
    assert restored.commit_sha == "abc123"
    assert restored.content_sha256 == content_sha256
    assert coordinator.current_snapshot is restored


def test_manifest_v2_requires_declared_required_files(tmp_path: Path) -> None:
    """v2 manifest 必须由 required_files 显式声明阻断发布的文件。"""

    (tmp_path / "fonts").mkdir()
    manifest = ResourceManifest(
        format_version=2,
        required_dirs=("fonts",),
        required_files=("data/required.json",),
        resource_version="6",
    )

    with pytest.raises(ResourceManifestError, match="必须文件不存在"):
        manifest.validate_root(tmp_path)


def test_manifest_v2_missing_optional_hashed_file_does_not_block(tmp_path: Path) -> None:
    """v2 的 file_hashes 只校验完整性，不能隐式把文件升级为必需资源。"""

    (tmp_path / "fonts").mkdir()
    manifest = ResourceManifest(
        format_version=2,
        required_dirs=("fonts",),
        required_files=(),
        resource_version="6",
        file_hashes={"textures/optional.png": "a" * 64},
    )

    manifest.validate_root(tmp_path)
    manifest.validate_file_hashes(tmp_path)


def test_manifest_v2_rejects_hash_mismatch_for_present_optional_file(
    tmp_path: Path,
) -> None:
    """可选文件一旦存在且声明摘要，内容不匹配仍必须拒绝发布。"""

    (tmp_path / "fonts").mkdir()
    asset = tmp_path / "textures" / "optional.png"
    asset.parent.mkdir()
    asset.write_bytes(b"actual")
    manifest = ResourceManifest(
        format_version=2,
        required_dirs=("fonts",),
        required_files=(),
        resource_version="6",
        file_hashes={"textures/optional.png": "a" * 64},
    )

    with pytest.raises(ResourceManifestError, match="文件哈希不匹配"):
        manifest.validate_file_hashes(tmp_path)


def test_manifest_v2_layout_is_declared_only_by_manifest(tmp_path: Path) -> None:
    """插件不得再维护一份与资源仓库重复的运行期目录清单。"""

    (tmp_path / "assets").mkdir()
    manifest = ResourceManifest(
        format_version=2,
        required_dirs=("assets",),
        required_files=(),
        resource_version="6",
    )

    assert manifest.validate_root(tmp_path) is manifest
