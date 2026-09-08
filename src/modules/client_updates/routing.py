"""客户端更新订阅的共享 Target 路由规则。

轮询编排和投递服务必须使用同一套订阅身份、元数据校验和目标固定规则，
避免事件落盘前后出现不同的目标集合。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from ...infrastructure.subscriptions import Subscription
from .contracts import ClientUpdateChange
from .state import ClientUpdatePendingTarget

logger = logging.getLogger(__name__)


def active_subscriptions(
    subscriptions: Sequence[Subscription],
) -> dict[tuple[str, str], tuple[Subscription, bool]]:
    """以最新记录覆盖同身份旧记录，并显式区分可投递与停用/损坏状态。"""

    active: dict[tuple[str, str], tuple[Subscription, bool]] = {}
    for subscription in subscriptions:
        key = (subscription.unified_msg_origin, subscription.uid)
        active[key] = (
            subscription,
            subscription.enabled and _has_valid_metadata(subscription),
        )
    return active


def pending_targets_for_change(
    change: ClientUpdateChange,
    subscriptions: Sequence[Subscription],
) -> tuple[ClientUpdatePendingTarget, ...]:
    """固定变化创建时所有有效启用订阅及其 Target 快照。"""

    if not isinstance(change, ClientUpdateChange):
        raise TypeError("change 必须是 ClientUpdateChange")

    latest = active_subscriptions(subscriptions)
    return tuple(
        ClientUpdatePendingTarget(
            origin=subscription.unified_msg_origin,
            uid=subscription.uid,
            bot_id=subscription.bot_id,
            target_ids=change.target_ids,
        )
        for subscription, routable in latest.values()
        if routable
    )


def _has_valid_metadata(subscription: Subscription) -> bool:
    """接受 target-neutral `{}` 与待生命周期清理的精确旧 platforms 形状。"""

    try:
        payload = json.loads(subscription.extra_data)
        if not isinstance(payload, dict):
            raise TypeError("订阅元数据必须是对象")
        if payload != {} and (
            set(payload) != {"platforms"} or not isinstance(payload["platforms"], list)
        ):
            raise TypeError("订阅元数据不是受支持的形状")
    except (TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "[dnaby][client_update] 订阅元数据无效，跳过投递（错误类型：%s）",
            type(error).__name__,
        )
        return False
    return True


__all__ = [
    "active_subscriptions",
    "pending_targets_for_change",
]
