"""密函与公告命令的用户可见文案。"""

from __future__ import annotations

NOTICES_CONTEXT_UNAVAILABLE = "通知查询上下文不可用"
NOTICES_SERVICE_UNAVAILABLE = "通知查询服务不可用"
NOTICES_UID_INVALID = "未登录或登录已失效，请重新登录"
NOTICES_PEEK_BLOCKED = "该用户开启了防偷窥，无法查看其游戏信息"
MH_NOT_FOUND = "未找到有效的密函数据"
ANN_LIST_FAILED = "获取公告列表失败"
ANN_INDEX_INVALID = "公告序号不正确，发送 公告 查看可用列表"
ANN_DETAIL_FAILED = "公告详情获取失败"

MH_SUBSCRIBE = "订阅二重螺旋密函"
MH_PIC_SUBSCRIBE = "订阅二重螺旋图片密函"
MH_TEXT_SUBSCRIBE = "订阅二重螺旋文本密函"
ANN_SUBSCRIBE = "订阅DNA公告"


def mh_all_forbidden(prefix: str = "kk") -> str:
    return f"禁止订阅全部密函, 请使用[{prefix}密函列表]命令查看可订阅密函"


def mh_push_time_format(prefix: str = "kk") -> str:
    return f"设置推送时间段格式错误，请使用以下格式\n例如开始时间:17点, 结束时间:23点, 命令: {prefix}订阅密函时间17:23"


COMMAND_PREFIX = "kk"
MH_ALL_FORBIDDEN = mh_all_forbidden(COMMAND_PREFIX)
MH_SUBSCRIBED_TEMPLATE = "成功订阅密函【{names}】"
MH_DUPLICATE = "请勿重复订阅密函【{name}】"
MH_UNSUBSCRIBED = "成功取消订阅密函【{name}】"
MH_UNSUBSCRIBED_ALL = "成功取消订阅全部密函!"
MH_NOT_SUBSCRIBED = "未曾订阅密函"
MH_SUBSCRIBE_EMPTY = "订阅列表为空"
MH_CURRENT = "当前订阅密函: {names}"
MH_PUSH_TIME_UNLIMITED = "推送时间: 不限制"
MH_PUSH_TIME_SET = "推送时间: {start}点-{end}点"
MH_PUSH_TIME_FORMAT = mh_push_time_format(COMMAND_PREFIX)
MH_PIC_SUBSCRIBED = "成功订阅密函图片"
MH_PIC_UNSUBSCRIBED = "成功取消订阅密函图片"
MH_PIC_NOT_SUBSCRIBED = "未曾订阅密函图片"
MH_TEXT_SUBSCRIBED = "成功订阅密函文本"
MH_TEXT_UNSUBSCRIBED = "成功取消订阅密函文本"
MH_TEXT_NOT_SUBSCRIBED = "未曾订阅密函文本"
ANN_GROUP_ONLY = "请在群聊中订阅"
ANN_GROUP_UNSUB_ONLY = "请在群聊中取消订阅"
ANN_ALREADY_SUBSCRIBED = "已经订阅了二重螺旋公告！"
ANN_SUBSCRIBED = "成功订阅二重螺旋公告！"
ANN_UNSUBSCRIBED = "成功取消订阅二重螺旋公告！"
ANN_NOT_SUBSCRIBED = "未曾订阅二重螺旋公告！"
ANN_POLL_INITIALIZED = "公告推送已初始化"

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
    "mh_all_forbidden",
    "mh_push_time_format",
]
