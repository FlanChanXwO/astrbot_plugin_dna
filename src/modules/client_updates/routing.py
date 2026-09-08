"""客户端更新订阅的共享路由规则。

轮询编排和投递服务必须使用同一套订阅身份、平台筛选和目标固定规则，
避免事件落盘前后出现不同的目标集合。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from ...infrastructure.subscriptions import Subscription
from .contracts import ClientPlatform, ClientUpdateChange
from .state import ClientUpdatePendingTarget

logger = logging.getLogger(__name__)


def active_subscriptions(
    subscriptions: Sequence[Subscription],
) -> dict[
    tuple[str, str],
    tuple[Subscription, tuple[ClientPlatform, ...] | None],
]:
    """以最新订阅记录覆盖同身份旧记录，保留停用状态供 pending 清理。"""

    active: dict[
        tuple[str, str],
        tuple[Subscription, tuple[ClientPlatform, ...] | None],
    ] = {}
    for subscription in subscriptions:
        key = (subscription.unified_msg_origin, subscription.uid)
        active[key] = (
            subscription,
            subscription_platforms(subscription) if subscription.enabled else None,
        )
    return active


def pending_targets_for_change(
    change: ClientUpdateChange,
    subscriptions: Sequence[Subscription],
) -> tuple[ClientUpdatePendingTarget, ...]:
    """固定变化创建时所有有效启用订阅及其 Target 快照。"""

    if not isinstance(change, ClientUpdateChange):
        raise TypeError("change 必须是 ClientUpdateChange")

    latest = {
        (subscription.unified_msg_origin, subscription.uid): subscription
        for subscription in subscriptions
    }
    pending: list[ClientUpdatePendingTarget] = []
    for subscription in latest.values():
        if not subscription.enabled or not _has_valid_metadata(subscription):
            continue
        pending.append(
            ClientUpdatePendingTarget(
                origin=subscription.unified_msg_origin,
                uid=subscription.uid,
                bot_id=subscription.bot_id,
                target_ids=change.target_ids,
            )
        )
    return tuple(pending)


def _has_valid_metadata(subscription: Subscription) -> bool:
    """新旧订阅元数据只要仍是 JSON 对象，就可在 T10 清理前参与投递。"""

    try:
        payload = json.loads(subscription.extra_data)
        if not isinstance(payload, dict):
            raise TypeError("订阅元数据必须是对象")
    except (TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "[dnaby][client_update] 订阅元数据无效，跳过投递（错误类型：%s）",
            type(error).__name__,
        )
        return False
    return True


def subscription_platforms(
    subscription: Subscription,
) -> tuple[ClientPlatform, ...] | None:
    """解析订阅记录中的平台筛选；非法元数据不参与投递。"""

    try:
        payload = json.loads(subscription.extra_data)
        if not isinstance(payload, dict):
            raise TypeError("订阅平台元数据必须是对象")
        raw_platforms = payload.get("platforms")
        if not isinstance(raw_platforms, list):
            raise TypeError("订阅平台元数据缺少 platforms 列表")
        selected = {ClientPlatform(value) for value in raw_platforms}
        if not selected:
            raise ValueError("订阅平台元数据为空")
        return tuple(
            platform
            for platform in (ClientPlatform.PC, ClientPlatform.ANDROID)
            if platform in selected
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        logger.warning(
            "[dnaby][client_update] 订阅平台元数据无效，跳过投递（错误类型：%s）",
            type(error).__name__,
        )
        return None


__all__ = [
    "active_subscriptions",
    "pending_targets_for_change",
    "subscription_platforms",
]
