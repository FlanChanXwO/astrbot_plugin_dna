"""面板图管理与资源状态命令的用户可见文案。"""

from __future__ import annotations

OPERATIONS_CONTEXT_UNAVAILABLE = "运维命令上下文不可用"
OPERATIONS_SERVICE_UNAVAILABLE = "运维服务不可用"
PANEL_IMAGE_REQUIRED = "请随命令发送一张面板图"
PANEL_CHAR_NOT_FOUND = "角色别名【{name}】不存在，请检查名称"
PANEL_CHAR_ID_NOT_FOUND = "角色【{name}】的CharId未找到"
PANEL_UPLOADED = "已上传{name}面板图{count}张"
PANEL_UPLOAD_FAILED = "面板图保存失败"
PANEL_EMPTY = "暂无{name}面板图"
PANEL_LIST_TITLE = "{name}面板图列表：共{count}张"
PANEL_DELETED = "已删除{name}面板图：{image_id}"
PANEL_DELETED_NOT_FOUND = "未找到{name}面板图：{image_id}"
PANEL_DELETED_ALL = "已删除{name}全部面板图：{count}张"
PANEL_DELETED_ALL_EMPTY = "暂无{name}面板图"
PANEL_COMPRESS_DONE = "面板图压缩完成：共{total}张，压缩{compressed}张，跳过{skipped}张"
PANEL_ORIGINAL_UNSUPPORTED = "当前平台暂不支持通过引用删除原图"
RESOURCE_STATUS_EMPTY = "私有资源仓库尚未同步到数据目录"
RESOURCE_STATUS_HEADER = "资源状态："


def resource_status_line(label: str, value: str) -> str:
    return f"{label}: {value}"


__all__ = [
    "OPERATIONS_CONTEXT_UNAVAILABLE",
    "OPERATIONS_SERVICE_UNAVAILABLE",
    "PANEL_CHAR_ID_NOT_FOUND",
    "PANEL_CHAR_NOT_FOUND",
    "PANEL_COMPRESS_DONE",
    "PANEL_DELETED",
    "PANEL_DELETED_ALL",
    "PANEL_DELETED_ALL_EMPTY",
    "PANEL_DELETED_NOT_FOUND",
    "PANEL_EMPTY",
    "PANEL_IMAGE_REQUIRED",
    "PANEL_LIST_TITLE",
    "PANEL_ORIGINAL_UNSUPPORTED",
    "PANEL_UPLOADED",
    "PANEL_UPLOAD_FAILED",
    "RESOURCE_STATUS_EMPTY",
    "RESOURCE_STATUS_HEADER",
    "resource_status_line",
]
