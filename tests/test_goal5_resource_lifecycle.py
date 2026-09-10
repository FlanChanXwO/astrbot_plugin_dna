"""Goal 5：资源归档、generation lease 与同步失败边界回归测试。"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import tarfile

import pytest

from src.infrastructure.resources import (
    ResourceGenerationError,
    ResourceManifest,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
    ResourceSyncError,
)
from src.infrastructure.resources.generation import (
    _extract_archive,
    _validate_declared_file_hashes,
)
from src.infrastructure.resources.manifest import RUNTIME_RESOURCE_DIRECTORIES


def _write_tar_member(
    archive_path: Path,
    name: str,
    *,
    member_type: int = tarfile.REGTYPE,
    linkname: str = "",
) -> None:
    with tarfile.open(archive_path, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.type = member_type
        member.linkname = linkname
        if member_type == tarfile.REGTYPE:
            member.size = 0
            archive.addfile(member, BytesIO())
        else:
            archive.addfile(member)


def _snapshot(coordinator: ResourceSnapshotCoordinator, commit_sha: str) -> ResourceSnapshot:
    root = coordinator.generations_root / commit_sha
    root.mkdir(parents=True, exist_ok=True)
    return ResourceSnapshot(
        commit_sha=commit_sha,
        root=root,
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("alias",),
            resource_version=commit_sha,
        ),
        player_resources=object(),
        encyclopedia_resources=object(),
    )


@pytest.mark.parametrize(
    "member_name",
    ("../escape.txt", "folder/../escape.txt", "/absolute.txt"),
)
def test_resource_archive_rejects_path_escape(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive_path = tmp_path / "candidate.tar"
    destination = tmp_path / "candidate"
    destination.mkdir()
    _write_tar_member(archive_path, member_name)

    with pytest.raises(ResourceGenerationError, match="路径"):
        _extract_archive(archive_path, destination)

    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "absolute.txt").exists()


def test_resource_archive_rejects_symlink_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "candidate.tar"
    destination = tmp_path / "candidate"
    destination.mkdir()
    _write_tar_member(
        archive_path,
        "images/escape.png",
        member_type=tarfile.SYMTYPE,
        linkname="../../outside.png",
    )

    with pytest.raises(ResourceGenerationError, match="文件类型"):
        _extract_archive(archive_path, destination)


def test_manifest_declared_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    resource = tmp_path / "images" / "card.png"
    resource.parent.mkdir()
    resource.write_bytes(b"card")
    manifest = ResourceManifest(
        format_version=1,
        required_dirs=RUNTIME_RESOURCE_DIRECTORIES,
        resource_version="v1",
        file_hashes={
            "images/card.png": hashlib.sha256(b"different").hexdigest(),
        },
    )

    with pytest.raises(ResourceGenerationError, match="哈希不匹配"):
        _validate_declared_file_hashes(tmp_path, manifest)


def test_generation_update_waits_for_old_snapshot_lease(tmp_path: Path) -> None:
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource-generations",
    )
    first = _snapshot(coordinator, "a" * 40)
    second = _snapshot(coordinator, "b" * 40)
    coordinator._activate(first)

    lease = coordinator.acquire()
    coordinator._activate(second)

    assert first.root.exists()
    assert coordinator.current_snapshot is second

    lease.release()

    assert not first.root.exists()
    assert second.root.exists()


def test_sync_failure_keeps_active_snapshot_and_records_safe_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource-generations",
    )
    active = _snapshot(coordinator, "c" * 40)
    coordinator._activate(active)

    def unavailable() -> object:
        raise ResourceSyncError("remote unavailable")

    monkeypatch.setattr(coordinator, "_sync_resources", unavailable)

    with pytest.raises(ResourceSyncError, match="remote unavailable"):
        coordinator.sync_resources()

    assert coordinator.current_snapshot is active
    assert coordinator.last_sync_status is not None
    assert coordinator.last_sync_status.status == "failed"
    assert coordinator.last_sync_status.error_type == "ResourceSyncError"
