"""签到命令的用户可见文案。"""

from __future__ import annotations

from .contracts import CheckinFailureKind, SignStatus

CHECKIN_CONTEXT_UNAVAILABLE = "签到查询上下文不可用"
CHECKIN_SERVICE_UNAVAILABLE = "签到服务不可用"
CHECKIN_UID_INVALID = "未登录或登录已失效，请重新登录"
CHECKIN_PEEK_BLOCKED = "该用户开启了防偷窥，无法查看其游戏信息"
CHECKIN_ALL_STARTED = "已开始执行全部签到"
CHECKIN_ALL_DONE = "全部签到执行完成"
CHECKIN_NO_USERS = "没有需要签到的用户"
CHECKIN_AUTO_ENABLED = "已开启当前 UID 的自动签到"
CHECKIN_AUTO_DISABLED = "已关闭当前 UID 的自动签到"
CHECKIN_ALREADY = "今日签到已完成，请勿重复签到"
CHECKIN_POSTS_EMPTY = "社区任务：帖子列表为空"
CHECKIN_TASKS_EMPTY = "社区任务列表为空，无法执行社区任务"
CHECKIN_DETAIL_FAILED = "社区任务：浏览帖子失败次数过多，请稍后重试"
CHECKIN_LIKE_FAILED = "社区任务：帖子点赞失败次数过多，请稍后重试"
CHECKIN_REPLY_FAILED = "社区任务：帖子回复失败次数过多，请稍后重试"

SIGN_RESULT_SUBSCRIBE = "订阅二重螺旋签到结果"
SIGN_RESULT_SUBSCRIBED = "已订阅签到结果推送"
SIGN_RESULT_UNSUBSCRIBED = "已取消订阅签到结果推送"
SIGN_RESULT_ORIGIN_MISSING = "无法定位当前会话，无法订阅签到结果"
SIGN_RESULT_STORE_UNAVAILABLE = "签到订阅存储不可用，请检查数据目录后重试"
SIGN_RESULT_EMPTY = "今日暂无自动签到结果"
SIGN_RESULT_CLEANED = "已清理过期签到记录"

SIGN_STATUS_TEXT = {
    SignStatus.DONE: "✅ 已完成",
    SignStatus.SKIP: "🚫 请勿重复签到",
    SignStatus.FAILED: "❌ 签到失败",
    SignStatus.DISABLED: "🚫 签到功能已关闭",
}

_COMMUNITY_LABELS = {
    "bbs_sign": "签到",
    "bbs_detail": "浏览",
    "bbs_like": "点赞",
    "bbs_share": "分享",
    "bbs_reply": "回复",
}

COMMUNITY_TASK_TARGETS = {
    "bbs_sign": 1,
    "bbs_detail": 3,
    "bbs_like": 5,
    "bbs_share": 1,
    "bbs_reply": 5,
}


def sign_status(status: SignStatus) -> str:
    return SIGN_STATUS_TEXT[status]


def community_label(mark_name: str) -> str:
    return _COMMUNITY_LABELS.get(mark_name, mark_name)


def community_target(mark_name: str) -> int:
    return COMMUNITY_TASK_TARGETS.get(mark_name, 1)


def transport_error(kind: CheckinFailureKind) -> str:
    """把稳定失败类别映射为受控文案，不暴露服务端原文。"""

    return {
        CheckinFailureKind.NETWORK: "签到请求网络异常，请稍后重试",
        CheckinFailureKind.STATUS: "签到服务响应异常",
        CheckinFailureKind.SERVER: "签到服务异常，请稍后重试",
        CheckinFailureKind.CREDENTIAL: "账号凭据无效，请重新登录",
        CheckinFailureKind.NOT_FOUND: "签到数据未找到",
    }[kind]


__all__ = [
    "CHECKIN_ALL_DONE",
    "CHECKIN_ALL_STARTED",
    "CHECKIN_ALREADY",
    "CHECKIN_AUTO_DISABLED",
    "CHECKIN_AUTO_ENABLED",
    "CHECKIN_CONTEXT_UNAVAILABLE",
    "CHECKIN_DETAIL_FAILED",
    "CHECKIN_LIKE_FAILED",
    "CHECKIN_NO_USERS",
    "CHECKIN_PEEK_BLOCKED",
    "CHECKIN_POSTS_EMPTY",
    "CHECKIN_REPLY_FAILED",
    "CHECKIN_SERVICE_UNAVAILABLE",
    "CHECKIN_TASKS_EMPTY",
    "CHECKIN_UID_INVALID",
    "SIGN_RESULT_CLEANED",
    "SIGN_RESULT_EMPTY",
    "SIGN_RESULT_ORIGIN_MISSING",
    "SIGN_RESULT_STORE_UNAVAILABLE",
    "SIGN_RESULT_SUBSCRIBE",
    "SIGN_RESULT_SUBSCRIBED",
    "SIGN_RESULT_UNSUBSCRIBED",
    "community_label",
    "community_target",
    "sign_status",
    "transport_error",
]
