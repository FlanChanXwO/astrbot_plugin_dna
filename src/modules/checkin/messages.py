"""签到命令的用户可见文案兼容层。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip
from .contracts import CheckinFailureKind, SignStatus

CHECKIN_CONTEXT_UNAVAILABLE = get_tip("checkin.context_unavailable")
CHECKIN_SERVICE_UNAVAILABLE = get_tip("checkin.service_unavailable")
CHECKIN_UID_INVALID = get_tip("checkin.uid_invalid")
CHECKIN_PEEK_BLOCKED = get_tip("checkin.peek_blocked")
CHECKIN_ALL_STARTED = get_tip("checkin.all_started")
CHECKIN_ALL_DONE = get_tip("checkin.all_done")
CHECKIN_NO_USERS = get_tip("checkin.no_users")
CHECKIN_AUTO_ENABLED = get_tip("checkin.auto_enabled")
CHECKIN_AUTO_DISABLED = get_tip("checkin.auto_disabled")
CHECKIN_ALREADY = get_tip("checkin.already")
CHECKIN_POSTS_EMPTY = get_tip("checkin.posts_empty")
CHECKIN_TASKS_EMPTY = get_tip("checkin.tasks_empty")
CHECKIN_DETAIL_FAILED = get_tip("checkin.detail_failed")
CHECKIN_LIKE_FAILED = get_tip("checkin.like_failed")
CHECKIN_REPLY_FAILED = get_tip("checkin.reply_failed")

# 这些值同时作为订阅类型，属于持久化域值，不能随运行期提示迁移。
SIGN_RESULT_SUBSCRIBE = "订阅二重螺旋签到结果"
SIGN_RESULT_SUBSCRIBED = get_tip("checkin.sign_result_subscribed")
SIGN_RESULT_UNSUBSCRIBED = get_tip("checkin.sign_result_unsubscribed")
SIGN_RESULT_ORIGIN_MISSING = get_tip("checkin.sign_result_origin_missing")
SIGN_RESULT_STORE_UNAVAILABLE = get_tip("checkin.sign_result_store_unavailable")
SIGN_RESULT_EMPTY = get_tip("checkin.sign_result_empty")
SIGN_RESULT_CLEANED = get_tip("checkin.sign_result_cleaned")

SIGN_STATUS_TEXT = {
    SignStatus.DONE: get_tip("checkin.status_done"),
    SignStatus.SKIP: get_tip("checkin.status_skip"),
    SignStatus.FAILED: get_tip("checkin.status_failed"),
    SignStatus.DISABLED: get_tip("checkin.status_disabled"),
}

_COMMUNITY_LABEL_KEYS = {
    "bbs_sign": "checkin.community_sign",
    "bbs_detail": "checkin.community_detail",
    "bbs_like": "checkin.community_like",
    "bbs_share": "checkin.community_share",
    "bbs_reply": "checkin.community_reply",
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


def sign_detail_status(status: SignStatus) -> str:
    return get_tip("checkin.detail_sign_status", status=sign_status(status))


def sign_detail_community_title() -> str:
    return get_tip("checkin.detail_community_title")


def sign_detail_error(error: str) -> str:
    return get_tip("checkin.detail_error", error=error)


def sign_detail_separator() -> str:
    return get_tip("checkin.detail_separator")


def all_summary(success: int, failed: int) -> str:
    return get_tip("checkin.all_summary", success=success, failed=failed)


def auto_summary(game_success: int, bbs_success: int) -> str:
    return get_tip(
        "checkin.auto_summary",
        game_success=game_success,
        bbs_success=bbs_success,
    )


def auto_task_header() -> str:
    return get_tip("checkin.auto_task_header")


def community_label(mark_name: str) -> str:
    key = _COMMUNITY_LABEL_KEYS.get(mark_name)
    return get_tip(key) if key else mark_name


def community_target(mark_name: str) -> int:
    return COMMUNITY_TASK_TARGETS.get(mark_name, 1)


def account_not_bound(*, target: bool = False) -> str:
    """生成本地账号绑定缺失文案。"""

    return get_tip(
        "common.target_account_not_bound" if target else "common.account_not_bound"
    )


def transport_error(kind: CheckinFailureKind, *, target: bool = False) -> str:
    """把稳定失败类别映射为受控文案，不暴露服务端原文。"""

    if kind is CheckinFailureKind.CREDENTIAL:
        return get_tip(
            "common.credential_invalid" if target else "common.login_expired"
        )
    key = {
        CheckinFailureKind.NETWORK: "checkin.transport_network",
        CheckinFailureKind.STATUS: "checkin.transport_status",
        CheckinFailureKind.SERVER: "checkin.transport_server",
        CheckinFailureKind.NOT_FOUND: "checkin.transport_not_found",
    }.get(kind)
    return get_tip(key) if key else get_tip("common.service_unavailable")


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
    "account_not_bound",
    "all_summary",
    "auto_summary",
    "auto_task_header",
    "community_label",
    "community_target",
    "sign_detail_community_title",
    "sign_detail_error",
    "sign_detail_separator",
    "sign_detail_status",
    "sign_status",
    "transport_error",
]
