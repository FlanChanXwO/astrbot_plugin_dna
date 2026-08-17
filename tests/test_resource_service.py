"""Task 26 资源更新与更新日志展示的隔离测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.response import PlainTextResponse
from src.infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSyncResult,
)
from src.modules.operations import messages
from src.modules.operations.resource_service import ResourceUpdateService


def _service(tmp_path: Path, *, synchronize=None, commit_log=None) -> ResourceUpdateService:
    return ResourceUpdateService(
        repo_root=tmp_path / "repo",
        synchronize=synchronize or (lambda: ResourceSyncResult(repository=tmp_path / "r", action="cloned", resource_version="1.0")),
        commit_log=commit_log or (lambda root: []),
    )

@pytest.mark.asyncio
async def test_download_all_reports_clone_and_update(tmp_path: Path) -> None:
    """下载成功区分克隆与更新动作并报告版本。"""

    cloned = _service(tmp_path, synchronize=lambda: ResourceSyncResult(repository=tmp_path, action="cloned", resource_version="1.0"))
    updated = _service(tmp_path, synchronize=lambda: ResourceSyncResult(repository=tmp_path, action="updated", resource_version="2.0"))

    clone_resp = await cloned.download_all(None)
    update_resp = await updated.download_all(None)

    assert isinstance(clone_resp, PlainTextResponse)
    assert "资源已克隆完成，版本 1.0" in clone_resp.text
    assert "资源已更新完成，版本 2.0" in update_resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GitUnavailableError(), "未找到 git 可执行文件"),
        (ResourceRemoteMismatchError(), "origin 与配置的私有资源仓库不一致"),
        (ResourceLocalChangesError("M panel/101.png"), "存在本地修改"),
        (ResourceSyncError("sync exploded"), "资源同步失败：sync exploded"),
    ],
)
async def test_download_all_failures_are_visible(tmp_path: Path, error: Exception, expected: str) -> None:
    """Git 缺失/远端不匹配/本地修改/同步失败均返回可见文案，不自动覆盖。"""

    def boom() -> ResourceSyncResult:
        raise error

    service = _service(tmp_path, synchronize=boom)
    response = await service.download_all(None)

    assert isinstance(response, PlainTextResponse)
    assert expected in response.text


@pytest.mark.asyncio
async def test_update_log_shows_commits_or_visible_failure(tmp_path: Path) -> None:
    """更新日志展示最近提交；Git 不可用返回可见失败。"""

    service = _service(tmp_path, commit_log=lambda root: ["abc123 fix resource", "def456 feat panel"])
    with_commits = await service.update_log(None)
    from src.entry.response import ImageResponse

    assert isinstance(with_commits, ImageResponse)

    empty_service = _service(tmp_path, commit_log=lambda root: [])
    empty = await empty_service.update_log(None)
    assert isinstance(empty, PlainTextResponse)
    assert empty.text == messages.UPDATE_LOG_UNAVAILABLE
