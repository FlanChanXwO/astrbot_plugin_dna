"""公共资源更新 use case。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ...entry.response import PlainTextResponse
from ...infrastructure.resources import (
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSyncResult,
)
from . import messages

SynchronizeFn = Callable[[], ResourceSyncResult]


class ResourceUpdateService:
    """公共资源同步。

    同步只调用参数列表形式的 ``git``（浅克隆 / ``pull --ff-only``），Git 缺失、认证失败、
    远端失败、非快进和本地修改均通过异常显露为可见文案，不自动覆盖本地修改。
    """

    def __init__(
        self,
        *,
        synchronize: SynchronizeFn,
    ) -> None:
        self.synchronize = synchronize

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

__all__ = ["ResourceUpdateService"]
