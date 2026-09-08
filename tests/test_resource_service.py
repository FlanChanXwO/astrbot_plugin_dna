"""Task 26 公共资源更新的隔离测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event, Lock

import pytest

from src.entry.response import PlainTextResponse
from src.infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSyncResult,
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
async def test_download_all_reports_clone_and_update(tmp_path: Path) -> None:
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
        (ResourceRemoteMismatchError(), "origin 与配置的公共资源仓库不一致"),
        (ResourceLocalChangesError("M panel/101.png"), "存在本地修改"),
        (ResourceSyncError("sync exploded"), "资源同步失败：sync exploded"),
    ],
)
async def test_download_all_failures_are_visible(
    tmp_path: Path, error: Exception, expected: str
) -> None:
    """Git 缺失/远端不匹配/本地修改/同步失败均返回可见文案，不自动覆盖。"""

    def boom() -> ResourceSyncResult:
        raise error

    service = _service(tmp_path, synchronize=boom)
    response = await service.download_all(None)

    assert isinstance(response, PlainTextResponse)
    assert expected in response.text


@pytest.mark.asyncio
async def test_concurrent_download_all_uses_one_single_flight(tmp_path: Path) -> None:
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
    first = asyncio.create_task(service.download_all(None))
    await asyncio.to_thread(started.wait)
    second = asyncio.create_task(service.download_all(None))
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
