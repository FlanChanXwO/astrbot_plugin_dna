"""资源更新与更新日志展示 use case。"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ...entry.response import ImageResponse, PlainTextResponse
from ...infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSyncResult,
)
from . import messages

SynchronizeFn = Callable[[], ResourceSyncResult]
CommitLogFn = Callable[[Path], list[str]]


def _git_log(repo_root: Path, *, limit: int = 20) -> list[str]:
    """读取插件仓库最近提交；git 缺失/非仓库/异常返回空列表（可见失败）。"""

    try:
        process = subprocess.run(
            ["git", "log", "--pretty=format:%h %s", f"-{limit}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return []
    if process.returncode != 0:
        return []
    commits = [line.strip() for line in (process.stdout or "").splitlines() if line.strip()]
    return commits[:limit]


class ResourceUpdateService:
    """公共资源同步与插件更新日志展示。

    同步只调用参数列表形式的 ``git``（浅克隆 / ``pull --ff-only``），Git 缺失、认证失败、
    远端失败、非快进和本地修改均通过异常显露为可见文案，不自动覆盖本地修改。
    """

    def __init__(
        self,
        *,
        repo_root: str | Path,
        synchronize: SynchronizeFn,
        commit_log: CommitLogFn = _git_log,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.synchronize = synchronize
        self.commit_log = commit_log

    async def download_all(self, _request: object):
        """下载全部公共资源（浅克隆或 ff-only 更新）。"""

        try:
            result = await asyncio.to_thread(self.synchronize)
        except ResourceLocalChangesError as error:
            return PlainTextResponse(messages.RESOURCE_LOCAL_CHANGES.format(detail=str(error)))
        except ResourceRemoteMismatchError:
            return PlainTextResponse(messages.RESOURCE_REMOTE_MISMATCH)
        except GitUnavailableError:
            return PlainTextResponse(messages.RESOURCE_GIT_UNAVAILABLE)
        except ResourceSyncError as error:
            return PlainTextResponse(messages.RESOURCE_SYNC_FAILED.format(detail=str(error)))
        action = "已克隆" if result.action == "cloned" else "已更新"
        return PlainTextResponse(messages.RESOURCE_DOWNLOADED.format(action=action, version=result.resource_version))

    async def update_log(self, _request: object):
        """读取插件仓库最近提交。"""

        from ...infrastructure.rendering.update_log import draw_update_log_img

        commits = await asyncio.to_thread(self.commit_log, self.repo_root)
        if not commits:
            return PlainTextResponse(messages.UPDATE_LOG_UNAVAILABLE)
        rendered = await draw_update_log_img(commits)
        if isinstance(rendered, bytes):
            with tempfile.NamedTemporaryFile(prefix="dnaby-update-log-更新记录-", suffix=".jpg", delete=False) as file:
                file.write(rendered)
                return ImageResponse(file.name, temporary=False)
        return PlainTextResponse(messages.UPDATE_LOG_TITLE + "\n" + "\n".join(commits))


__all__ = ["ResourceUpdateService"]
