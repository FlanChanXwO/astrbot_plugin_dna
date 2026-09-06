"""公共资源管理命令的用户可见文案兼容层。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip, get_tip_template

OPERATIONS_CONTEXT_UNAVAILABLE = get_tip("operations.context_unavailable")
OPERATIONS_SERVICE_UNAVAILABLE = get_tip("operations.service_unavailable")
RESOURCE_STATUS_EMPTY = get_tip("operations.resource_status_empty")
RESOURCE_STATUS_HEADER = get_tip("operations.resource_status_header")
RESOURCE_STATUS_REPOSITORY_PATH = get_tip("operations.resource_status_repository_path")
RESOURCE_STATUS_GENERATION_ID = get_tip("operations.resource_status_generation_id")
RESOURCE_STATUS_ACTIVE_POINTER = get_tip("operations.resource_status_active_pointer")
RESOURCE_STATUS_RESOURCE_VERSION = get_tip(
    "operations.resource_status_resource_version"
)
RESOURCE_STATUS_LAST_SYNC_RESULT = get_tip(
    "operations.resource_status_last_sync_result"
)
RESOURCE_STATUS_UNPUBLISHED = get_tip("operations.resource_status_unpublished")
RESOURCE_STATUS_UNKNOWN = get_tip("operations.resource_status_unknown")
RESOURCE_STATUS_UNRECORDED = get_tip("operations.resource_status_unrecorded")
RESOURCE_STATUS_UNAVAILABLE = get_tip("operations.resource_status_unavailable")
RESOURCE_STATUS_SYNC_SUCCESS = get_tip_template(
    "operations.resource_status_sync_success"
)
RESOURCE_STATUS_SYNC_FAILED = get_tip_template("operations.resource_status_sync_failed")
RESOURCE_STATUS_SYNC_UNREADABLE = get_tip("operations.resource_status_sync_unreadable")
RESOURCE_GIT_UNAVAILABLE = get_tip("operations.resource_git_unavailable")
RESOURCE_REMOTE_MISMATCH = get_tip("operations.resource_remote_mismatch")
RESOURCE_LOCAL_CHANGES = get_tip_template("operations.resource_local_changes")
RESOURCE_SYNC_FAILED = get_tip_template("operations.resource_sync_failed")
RESOURCE_DOWNLOADED = get_tip_template("operations.resource_downloaded")
RESOURCE_UP_TO_DATE = get_tip_template("operations.resource_up_to_date")


def resource_status_line(label: str, value: str) -> str:
    return get_tip("operations.resource_status_line", label=label, value=value)


__all__ = [
    "OPERATIONS_CONTEXT_UNAVAILABLE",
    "OPERATIONS_SERVICE_UNAVAILABLE",
    "RESOURCE_DOWNLOADED",
    "RESOURCE_GIT_UNAVAILABLE",
    "RESOURCE_LOCAL_CHANGES",
    "RESOURCE_REMOTE_MISMATCH",
    "RESOURCE_STATUS_ACTIVE_POINTER",
    "RESOURCE_STATUS_GENERATION_ID",
    "RESOURCE_STATUS_LAST_SYNC_RESULT",
    "RESOURCE_STATUS_REPOSITORY_PATH",
    "RESOURCE_STATUS_RESOURCE_VERSION",
    "RESOURCE_STATUS_SYNC_FAILED",
    "RESOURCE_STATUS_SYNC_SUCCESS",
    "RESOURCE_STATUS_SYNC_UNREADABLE",
    "RESOURCE_STATUS_UNAVAILABLE",
    "RESOURCE_STATUS_UNPUBLISHED",
    "RESOURCE_STATUS_UNKNOWN",
    "RESOURCE_STATUS_UNRECORDED",
    "RESOURCE_STATUS_EMPTY",
    "RESOURCE_STATUS_HEADER",
    "RESOURCE_SYNC_FAILED",
    "RESOURCE_UP_TO_DATE",
    "resource_status_line",
]
