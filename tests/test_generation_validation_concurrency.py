"""资源同步完整校验期间的已发布 generation 可见性回归。

``validate_current()`` 只对当前已发布 generation 重新做完整校验。校验必须
在 state lock 之外执行，期间物理目录仍存在且此前已验证通过，因此新面板
渲染必须继续取得该 generation；只有校验真正失败时才能撤下 current。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.rendering.player import ResourceMap
from src.infrastructure.resources import (
    ResourceGenerationError,
    ResourceManifest,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore

COMMIT_SHA = "a" * 40
CONTENT_SHA256 = "b" * 64


def _published_coordinator(tmp_path: Path) -> tuple[ResourceSnapshotCoordinator, ResourceSnapshot]:
    """建立一个已原子发布 current 的 coordinator。"""

    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "repository",
        generations_root=tmp_path / "generations",
    )
    snapshot = ResourceSnapshot(
        commit_sha=COMMIT_SHA,
        root=tmp_path / "generation",
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("images",),
            resource_version="test",
        ),
        player_resources=ResourceMap(),
        encyclopedia_resources=EncyclopediaResourceStore(),
        content_sha256=CONTENT_SHA256,
    )
    coordinator._current = snapshot
    coordinator._loaded_snapshot = snapshot
    coordinator._expected_content_sha256 = CONTENT_SHA256
    return coordinator, snapshot


def _stub_validator(coordinator: ResourceSnapshotCoordinator, validate) -> None:
    coordinator._validator = SimpleNamespace(validate=validate)


def test_validate_current_keeps_published_generation_serving(tmp_path: Path) -> None:
    """校验执行期间，新请求仍能取得已发布 current（面板不进入 placeholder）。"""

    coordinator, snapshot = _published_coordinator(tmp_path)
    observed: list[object] = []

    def validate(_root: Path, _commit_sha: str) -> ResourceSnapshot:
        observed.append(coordinator.current_snapshot)
        with coordinator.acquire() as leased:
            observed.append(leased.commit_sha)
        with coordinator.optional_lease() as optional:
            observed.append(optional)
        return snapshot

    _stub_validator(coordinator, validate)

    validated = coordinator.validate_current()

    assert observed[0] is snapshot, "校验期间 current 被提前撤下"
    assert observed[1] == COMMIT_SHA
    assert observed[2] is snapshot, "校验期间 optional_lease 拿不到已发布快照"
    assert validated is snapshot
    assert coordinator.current_snapshot is snapshot


def test_validate_current_removes_current_only_after_validation_fails(
    tmp_path: Path,
) -> None:
    """校验失败后才撤下 current，并保持既有失败/修复语义。"""

    coordinator, snapshot = _published_coordinator(tmp_path)
    observed: list[object] = []

    def validate(_root: Path, _commit_sha: str) -> ResourceSnapshot:
        observed.append(coordinator.current_snapshot)
        raise ResourceGenerationError("资源候选 generation 校验失败")

    _stub_validator(coordinator, validate)

    with pytest.raises(ResourceGenerationError):
        coordinator.validate_current()

    assert observed[0] is snapshot, "校验尚未失败时 current 不应被撤下"
    assert coordinator.current_snapshot is None
    with pytest.raises(ResourceGenerationError, match="没有可用的已验证资源 generation"):
        coordinator.acquire()


def test_validate_current_keeps_held_lease_intact(tmp_path: Path) -> None:
    """校验不使已持有 lease 失效，lease 计数仍按既有语义释放。"""

    coordinator, snapshot = _published_coordinator(tmp_path)
    with coordinator.acquire() as leased:
        _stub_validator(coordinator, lambda _root, _commit_sha: snapshot)

        coordinator.validate_current()

        assert leased is snapshot
        assert coordinator.current_snapshot is snapshot
        assert coordinator._leases == {COMMIT_SHA: 1}

    assert coordinator._leases == {}
