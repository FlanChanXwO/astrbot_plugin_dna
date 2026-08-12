"""密函与公告命令的用户可见文案。"""

from __future__ import annotations

from .contracts import NoticesFailureKind

NOTICES_CONTEXT_UNAVAILABLE = "通知查询上下文不可用"
NOTICES_SERVICE_UNAVAILABLE = "通知查询服务不可用"
NOTICES_UID_INVALID = "UID无效，请重新绑定"
NOTICES_PEEK_BLOCKED = "该用户开启了防偷窥，无法查看其游戏信息"
MH_NOT_FOUND = "未找到有效的密函数据"
ANN_LIST_FAILED = "获取公告列表失败"
ANN_INDEX_INVALID = "公告序号不正确，发送 公告 查看可用列表"
ANN_DETAIL_FAILED = "公告详情获取失败"


def transport_error(kind: NoticesFailureKind) -> str:
    """把稳定失败类别映射为受控文案，不暴露服务端原文。"""

    return {
        NoticesFailureKind.NETWORK: "通知请求网络异常，请稍后重试",
        NoticesFailureKind.STATUS: "通知服务响应异常",
        NoticesFailureKind.SERVER: "通知服务异常，请稍后重试",
        NoticesFailureKind.CREDENTIAL: "账号凭据无效，请重新登录",
        NoticesFailureKind.NOT_FOUND: "通知数据未找到",
    }[kind]


__all__ = [
    "ANN_DETAIL_FAILED",
    "ANN_INDEX_INVALID",
    "ANN_LIST_FAILED",
    "MH_NOT_FOUND",
    "NOTICES_CONTEXT_UNAVAILABLE",
    "NOTICES_PEEK_BLOCKED",
    "NOTICES_SERVICE_UNAVAILABLE",
    "NOTICES_UID_INVALID",
    "transport_error",
]
