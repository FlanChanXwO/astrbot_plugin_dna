"""公共资源更新 use case。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from astrbot.api import logger

from ...entry.response import PlainTextResponse
from ...infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceManifest,
    ResourceRemoteMismatchError,
    ResourceSnapshotCoordinator,
    ResourceStatusSnapshot,
    ResourceSyncError,
    ResourceSyncResult,
)
from . import messages

SynchronizeFn = Callable[[], ResourceSyncResult]


class ResourceUpdateService:
    """公共资源同步。

    同步只调用参数列表形式的 ``git``（浅克隆 / ``fetch`` / 候选校验 / fast-forward），
    Git 缺失、认证失败、远端失败、候选无效、非快进和本地修改均通过异常显露为可见文案，
    不自动覆盖本地修改。
    """

    def __init__(
        self,
        *,
        synchronize: SynchronizeFn,
        resource_root: str | Path | None = None,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
    ) -> None:
        self.synchronize = synchronize
        self.resource_root = Path(resource_root) if resource_root is not None else None
        self.resource_snapshots = resource_snapshots
        self._flight_lock = asyncio.Lock()
        self._inflight: asyncio.Task[ResourceSyncResult] | None = None
        self._stopping = False

    async def synchronize_once(self) -> ResourceSyncResult:
        """取得共享同步任务；取消单个等待者不会取消底层同步。"""

        async with self._flight_lock:
            if self._stopping:
                raise ResourceSyncError("资源同步服务正在停止")
            task = self._inflight
            if task is None or task.done():
                task = asyncio.create_task(asyncio.to_thread(self.synchronize))
                # 等待者全部取消后仍需消费线程任务的异常，避免 asyncio 只报未观察异常。
                task.add_done_callback(self._observe_sync_task)
                self._inflight = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._flight_lock:
                    if self._inflight is task:
                        self._inflight = None

    async def stop(self) -> None:
        """停止接受新同步，并等待正在运行的线程任务自然完成。"""

        async with self._flight_lock:
            self._stopping = True
            task = self._inflight
            if task is None or task.done():
                if task is not None and self._inflight is task:
                    self._inflight = None
                return

        try:
            # 线程任务无法安全取消；终止流程必须等待它释放资源后再继续。
            await asyncio.shield(task)
        finally:
            async with self._flight_lock:
                if self._inflight is task:
                    self._inflight = None

    @staticmethod
    def _observe_sync_task(task: asyncio.Task[ResourceSyncResult]) -> None:
        """观察取消等待者后仍在运行的同步任务，并保留真实失败日志。"""

        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.warning(f"[dnaby][resources] 共享资源同步任务失败: {error}")

    async def sync_resources(self, _request: object):
        """同步全部公共资源（浅克隆或 ff-only 更新）。"""

        try:
            result = await self.synchronize_once()
        except ResourceLocalChangesError as error:
            return PlainTextResponse(
                messages.RESOURCE_LOCAL_CHANGES.format(detail=str(error))
            )
        except ResourceRemoteMismatchError:
            return PlainTextResponse(messages.RESOURCE_REMOTE_MISMATCH)
        except GitUnavailableError:
            return PlainTextResponse(messages.RESOURCE_GIT_UNAVAILABLE)
        except ResourceSyncError as error:
            return PlainTextResponse(
                messages.RESOURCE_SYNC_FAILED.format(detail=str(error))
            )
        if result.action == "unchanged":
            return PlainTextResponse(
                messages.RESOURCE_UP_TO_DATE.format(version=result.resource_version),
            )
        action = "已克隆" if result.action == "cloned" else "已更新"
        return PlainTextResponse(
            messages.RESOURCE_DOWNLOADED.format(
                action=action,
                version=result.resource_version,
            ),
        )

    async def download_all(self, _request: object):
        """兼容旧命令入口，转发到 ``sync_resources``。"""

        return await self.sync_resources(_request)

    async def status(self):
        """展示公共资源状态；不读取已移除的自定义面板目录。"""

        if self.resource_snapshots is None:
            return self._status_response(self.resource_root)
        with self.resource_snapshots.optional_lease() as snapshot:
            reader = getattr(self.resource_snapshots, "read_status", None)
            if callable(reader):
                status = reader(snapshot)
                return self._status_snapshot_response(status)
            root = snapshot.root if snapshot is not None else self.resource_root
            return self._status_response(root)

    @staticmethod
    def _last_sync_summary(status: ResourceStatusSnapshot) -> str:
        if status.last_sync_error is not None:
            return messages.RESOURCE_STATUS_SYNC_UNREADABLE
        if status.last_sync is None:
            return messages.RESOURCE_STATUS_UNRECORDED
        if status.last_sync.status == "success":
            return messages.RESOURCE_STATUS_SYNC_SUCCESS.format(
                action=status.last_sync.action or messages.RESOURCE_STATUS_UNKNOWN,
                version=(
                    status.last_sync.resource_version
                    or messages.RESOURCE_STATUS_UNKNOWN
                ),
                generation=status.last_sync.commit_sha
                or messages.RESOURCE_STATUS_UNKNOWN,
            )
        return messages.RESOURCE_STATUS_SYNC_FAILED.format(
            error_type=status.last_sync.error_type or messages.RESOURCE_STATUS_UNKNOWN,
        )

    @classmethod
    def _status_snapshot_response(
        cls,
        status: ResourceStatusSnapshot,
    ) -> PlainTextResponse:
        lines = [messages.RESOURCE_STATUS_HEADER]
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_REPOSITORY_PATH,
                str(status.repository),
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_GENERATION_ID,
                status.generation_id or messages.RESOURCE_STATUS_UNPUBLISHED,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_ACTIVE_POINTER,
                str(status.active_pointer),
            )
        )
        if status.generation_id is None:
            active_version = messages.RESOURCE_STATUS_UNPUBLISHED
        elif status.manifest_state == "ready" and status.manifest is not None:
            active_version = status.manifest.resource_version
        else:
            active_version = messages.RESOURCE_STATUS_UNKNOWN
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_RESOURCE_VERSION,
                active_version,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_LAST_SYNC_RESULT,
                cls._last_sync_summary(status),
            )
        )

        if status.resource_root is None:
            if status.manifest_state == "missing":
                lines.append(messages.resource_status_line("manifest", "缺失"))
            lines.append(messages.RESOURCE_STATUS_EMPTY)
            return PlainTextResponse("\n".join(lines))
        if status.manifest_state == "missing":
            lines.append(messages.resource_status_line("manifest", "缺失"))
            return PlainTextResponse("\n".join(lines))
        if status.manifest_state == "corrupt":
            lines.append(messages.resource_status_line("manifest", "损坏或不可读"))
            return PlainTextResponse("\n".join(lines))
        if status.manifest_state == "unavailable":
            lines.append(
                messages.resource_status_line(
                    "manifest",
                    messages.RESOURCE_STATUS_UNAVAILABLE,
                )
            )
            return PlainTextResponse("\n".join(lines))
        assert status.manifest is not None
        lines.append(
            messages.resource_status_line(
                "manifest",
                f"v{status.manifest.format_version}",
            )
        )
        lines.append(
            messages.resource_status_line(
                "资源版本",
                status.manifest.resource_version,
            )
        )
        present = [
            directory
            for directory in status.manifest.required_dirs
            if (status.resource_root / directory).is_dir()
        ]
        lines.append(
            messages.resource_status_line(
                "必需目录",
                f"{len(present)}/{len(status.manifest.required_dirs)} 存在",
            ),
        )
        return PlainTextResponse("\n".join(lines))

    @staticmethod
    def _status_response(resource_root: Path | None) -> PlainTextResponse:
        lines = [messages.RESOURCE_STATUS_HEADER]
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_REPOSITORY_PATH,
                str(resource_root)
                if resource_root is not None
                else messages.RESOURCE_STATUS_UNKNOWN,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_GENERATION_ID,
                messages.RESOURCE_STATUS_UNPUBLISHED,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_ACTIVE_POINTER,
                messages.RESOURCE_STATUS_UNKNOWN,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_RESOURCE_VERSION,
                messages.RESOURCE_STATUS_UNPUBLISHED,
            )
        )
        lines.append(
            messages.resource_status_line(
                messages.RESOURCE_STATUS_LAST_SYNC_RESULT,
                messages.RESOURCE_STATUS_UNRECORDED,
            )
        )

        if resource_root is None or not resource_root.is_dir():
            lines.append(messages.RESOURCE_STATUS_EMPTY)
            return PlainTextResponse("\n".join(lines))

        manifest_path = resource_root / "resource_manifest.json"
        if not manifest_path.is_file():
            lines.append(messages.resource_status_line("manifest", "缺失"))
            return PlainTextResponse("\n".join(lines))
        try:
            manifest = ResourceManifest.load(manifest_path)
        except (OSError, UnicodeError, ValueError, TypeError):
            lines.append(messages.resource_status_line("manifest", "损坏或不可读"))
            return PlainTextResponse("\n".join(lines))
        lines[4] = messages.resource_status_line(
            messages.RESOURCE_STATUS_RESOURCE_VERSION,
            manifest.resource_version,
        )
        lines.append(
            messages.resource_status_line("manifest", f"v{manifest.format_version}")
        )
        lines.append(
            messages.resource_status_line("资源版本", manifest.resource_version)
        )
        present = [
            directory
            for directory in manifest.required_dirs
            if (resource_root / directory).is_dir()
        ]
        lines.append(
            messages.resource_status_line(
                "必需目录",
                f"{len(present)}/{len(manifest.required_dirs)} 存在",
            ),
        )
        return PlainTextResponse("\n".join(lines))


__all__ = ["ResourceUpdateService"]
