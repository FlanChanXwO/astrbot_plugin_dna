"""公共资源管理命令的用户可见文案兼容层。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip, get_tip_template

OPERATIONS_CONTEXT_UNAVAILABLE = get_tip("operations.context_unavailable")
OPERATIONS_SERVICE_UNAVAILABLE = get_tip("operations.service_unavailable")
RESOURCE_SYNC_STARTED = get_tip("operations.resource_sync_started")
RESOURCE_STATUS_EMPTY = get_tip("operations.resource_status_empty")
RESOURCE_STATUS_HEADER = get_tip("operations.resource_status_header")
RESOURCE_GIT_UNAVAILABLE = get_tip("operations.resource_git_unavailable")
RESOURCE_REMOTE_MISMATCH = get_tip("operations.resource_remote_mismatch")
RESOURCE_LOCAL_CHANGES = get_tip_template("operations.resource_local_changes")
RESOURCE_SYNC_FAILED = get_tip_template("operations.resource_sync_failed")
RESOURCE_DOWNLOADED = get_tip_template("operations.resource_downloaded")


def resource_status_line(label: str, value: str) -> str:
    return get_tip("operations.resource_status_line", label=label, value=value)


__all__ = [
    "OPERATIONS_CONTEXT_UNAVAILABLE",
    "OPERATIONS_SERVICE_UNAVAILABLE",
    "RESOURCE_DOWNLOADED",
    "RESOURCE_SYNC_STARTED",
    "RESOURCE_GIT_UNAVAILABLE",
    "RESOURCE_LOCAL_CHANGES",
    "RESOURCE_REMOTE_MISMATCH",
    "RESOURCE_STATUS_EMPTY",
    "RESOURCE_STATUS_HEADER",
    "RESOURCE_SYNC_FAILED",
    "resource_status_line",
]
