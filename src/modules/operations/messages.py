"""公共资源管理命令的用户可见文案。"""

from __future__ import annotations

OPERATIONS_CONTEXT_UNAVAILABLE = "运维命令上下文不可用"
OPERATIONS_SERVICE_UNAVAILABLE = "运维服务不可用"
RESOURCE_STATUS_EMPTY = "公共资源仓库尚未同步到数据目录"
RESOURCE_STATUS_HEADER = "资源状态："
RESOURCE_GIT_UNAVAILABLE = "未找到 git 可执行文件，无法同步公共资源仓库"
RESOURCE_REMOTE_MISMATCH = "资源 Git origin 与配置的公共资源仓库不一致"
RESOURCE_LOCAL_CHANGES = "{detail}"
RESOURCE_SYNC_FAILED = "资源同步失败：{detail}"
RESOURCE_DOWNLOADED = "资源{action}完成，版本 {version}"
def resource_status_line(label: str, value: str) -> str:
    return f"{label}: {value}"


__all__ = [
    "OPERATIONS_CONTEXT_UNAVAILABLE",
    "OPERATIONS_SERVICE_UNAVAILABLE",
    "RESOURCE_DOWNLOADED",
    "RESOURCE_GIT_UNAVAILABLE",
    "RESOURCE_LOCAL_CHANGES",
    "RESOURCE_REMOTE_MISMATCH",
    "RESOURCE_STATUS_EMPTY",
    "RESOURCE_STATUS_HEADER",
    "RESOURCE_SYNC_FAILED",
    "resource_status_line",
]
