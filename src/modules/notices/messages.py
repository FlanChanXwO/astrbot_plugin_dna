"""密函与公告命令的用户可见文案兼容层。"""

from __future__ import annotations

from ...infrastructure.i18n import get_tip, get_tip_template

NOTICES_CONTEXT_UNAVAILABLE = get_tip("notices.context_unavailable")
NOTICES_SERVICE_UNAVAILABLE = get_tip("notices.service_unavailable")
NOTICES_UID_INVALID = get_tip("notices.uid_invalid")
NOTICES_PEEK_BLOCKED = get_tip("notices.peek_blocked")
MH_NOT_FOUND = get_tip("notices.mh_not_found")
ANN_LIST_FAILED = get_tip("notices.ann_list_failed")
ANN_INDEX_INVALID = get_tip("notices.ann_index_invalid")
ANN_DETAIL_FAILED = get_tip("notices.ann_detail_failed")

# 这些值同时作为订阅类型，属于持久化域值，不能随运行期提示迁移。
MH_SUBSCRIBE = "订阅二重螺旋密函"
MH_PIC_SUBSCRIBE = "订阅二重螺旋图片密函"
MH_TEXT_SUBSCRIBE = "订阅二重螺旋文本密函"
ANN_SUBSCRIBE = "订阅DNA公告"


def account_not_bound(*, target: bool = False) -> str:
    """生成本地账号绑定缺失文案。"""

    return get_tip(
        "common.target_account_not_bound" if target else "common.account_not_bound"
    )


def transport_error(kind: str, *, target: bool = False) -> str:
    """按安全失败类别生成稳定文案，不暴露上游错误原文。"""

    if kind == "credential":
        return get_tip(
            "common.credential_invalid" if target else "common.login_expired"
        )
    return get_tip("common.service_unavailable")


def mh_all_forbidden(prefix: str = "kk") -> str:
    return get_tip("notices.mh_all_forbidden", prefix=prefix)


def mh_push_time_format(prefix: str = "kk") -> str:
    return get_tip("notices.mh_push_time_format", prefix=prefix)


def mh_subscribed_current(name: str, names: str) -> str:
    return get_tip("notices.mh_subscribed_current", name=name, names=names)


def mh_unsubscribed_current(name: str, names: str) -> str:
    return get_tip("notices.mh_unsubscribed_current", name=name, names=names)


def mh_unsubscribed_empty_current(name: str) -> str:
    return get_tip("notices.mh_unsubscribed_empty_current", name=name)


def mh_push_time_hint(prefix: str) -> str:
    return get_tip("notices.mh_push_time_hint", prefix=prefix)


def mh_list_item(type_name: str, name: str) -> str:
    return get_tip("notices.mh_list_item", type_name=type_name, name=name)


def mh_text_section(type_name: str) -> str:
    return get_tip("notices.mh_text_section", type_name=type_name)


def mh_text_item(index: int, name: str) -> str:
    return get_tip("notices.mh_text_item", index=index, name=name)


def mh_refresh_title() -> str:
    return get_tip("notices.mh_refresh_title")


def mh_text_title() -> str:
    return get_tip("notices.mh_text_title")


COMMAND_PREFIX = "kk"
MH_ALL_FORBIDDEN = mh_all_forbidden(COMMAND_PREFIX)
MH_SUBSCRIBED_TEMPLATE = get_tip_template("notices.mh_subscribed")
MH_DUPLICATE = get_tip_template("notices.mh_duplicate")
MH_UNSUBSCRIBED = get_tip_template("notices.mh_unsubscribed")
MH_UNSUBSCRIBED_ALL = get_tip("notices.mh_unsubscribed_all")
MH_NOT_SUBSCRIBED = get_tip("notices.mh_not_subscribed")
MH_SUBSCRIBE_EMPTY = get_tip("notices.mh_subscribe_empty")
MH_CURRENT = get_tip_template("notices.mh_current")
MH_PUSH_TIME_UNLIMITED = get_tip("notices.mh_push_time_unlimited")
MH_PUSH_TIME_SET = get_tip_template("notices.mh_push_time_set")
MH_PUSH_TIME_FORMAT = mh_push_time_format(COMMAND_PREFIX)
MH_PIC_SUBSCRIBED = get_tip("notices.mh_pic_subscribed")
MH_PIC_UNSUBSCRIBED = get_tip("notices.mh_pic_unsubscribed")
MH_PIC_NOT_SUBSCRIBED = get_tip("notices.mh_pic_not_subscribed")
MH_TEXT_SUBSCRIBED = get_tip("notices.mh_text_subscribed")
MH_TEXT_UNSUBSCRIBED = get_tip("notices.mh_text_unsubscribed")
MH_TEXT_NOT_SUBSCRIBED = get_tip("notices.mh_text_not_subscribed")
ANN_GROUP_ONLY = get_tip("notices.ann_group_only")
ANN_GROUP_UNSUB_ONLY = get_tip("notices.ann_group_unsub_only")
ANN_ALREADY_SUBSCRIBED = get_tip("notices.ann_already_subscribed")
ANN_SUBSCRIBED = get_tip("notices.ann_subscribed")
ANN_UNSUBSCRIBED = get_tip("notices.ann_unsubscribed")
ANN_NOT_SUBSCRIBED = get_tip("notices.ann_not_subscribed")
ANN_POLL_INITIALIZED = get_tip("notices.ann_poll_initialized")


__all__ = [
    "ANN_ALREADY_SUBSCRIBED",
    "ANN_DETAIL_FAILED",
    "ANN_GROUP_ONLY",
    "ANN_GROUP_UNSUB_ONLY",
    "ANN_INDEX_INVALID",
    "ANN_LIST_FAILED",
    "ANN_NOT_SUBSCRIBED",
    "ANN_POLL_INITIALIZED",
    "ANN_SUBSCRIBE",
    "ANN_SUBSCRIBED",
    "ANN_UNSUBSCRIBED",
    "COMMAND_PREFIX",
    "MH_ALL_FORBIDDEN",
    "MH_CURRENT",
    "MH_DUPLICATE",
    "MH_NOT_FOUND",
    "MH_NOT_SUBSCRIBED",
    "MH_PIC_NOT_SUBSCRIBED",
    "MH_PIC_SUBSCRIBE",
    "MH_PIC_SUBSCRIBED",
    "MH_PIC_UNSUBSCRIBED",
    "MH_PUSH_TIME_FORMAT",
    "MH_PUSH_TIME_SET",
    "MH_PUSH_TIME_UNLIMITED",
    "MH_SUBSCRIBE",
    "MH_SUBSCRIBED_TEMPLATE",
    "MH_SUBSCRIBE_EMPTY",
    "MH_TEXT_NOT_SUBSCRIBED",
    "MH_TEXT_SUBSCRIBE",
    "MH_TEXT_SUBSCRIBED",
    "MH_TEXT_UNSUBSCRIBED",
    "MH_UNSUBSCRIBED",
    "MH_UNSUBSCRIBED_ALL",
    "NOTICES_CONTEXT_UNAVAILABLE",
    "NOTICES_PEEK_BLOCKED",
    "NOTICES_SERVICE_UNAVAILABLE",
    "NOTICES_UID_INVALID",
    "account_not_bound",
    "mh_all_forbidden",
    "mh_list_item",
    "mh_push_time_format",
    "mh_push_time_hint",
    "mh_refresh_title",
    "mh_subscribed_current",
    "mh_text_item",
    "mh_text_section",
    "mh_text_title",
    "mh_unsubscribed_current",
    "mh_unsubscribed_empty_current",
    "transport_error",
]
