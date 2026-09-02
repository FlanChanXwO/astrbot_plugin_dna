"""客户端更新的框架无关推送 DTO 与注入式投递适配器。

领域层只负责按照订阅筛选平台消息，并把消息交给最小化的推送端口。OneBot
节点的具体构造留在注入的 ``send_forward`` 回调中；这里不导入 AstrBot 消息
组件，避免客户端更新 use case 与宿主框架耦合。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from . import messages
from .contracts import ClientPlatform, ClientUpdateChange

logger = logging.getLogger(__name__)

_CLIENT_PLATFORM_ORDER = {
    ClientPlatform.PC: 0,
    ClientPlatform.ANDROID: 1,
}

SenderResult = bool | None
TextSender = Callable[[str, str], Awaitable[SenderResult]]
ForwardSender = Callable[[str, tuple[str, ...]], Awaitable[SenderResult]]


@dataclass(frozen=True, slots=True)
class ClientUpdatePushTarget:
    """一个订阅目标的最小路由信息。"""

    origin: str
    bot_id: str


@dataclass(frozen=True, slots=True)
class ClientUpdatePushMessage:
    """一个平台对应的一条用户可见更新消息。"""

    platform: ClientPlatform
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", ClientPlatform(self.platform))
        if not isinstance(self.text, str):
            raise TypeError("text 必须是字符串")


@dataclass(frozen=True, slots=True)
class ClientUpdatePush:
    """发往单个订阅目标的一轮客户端更新消息。"""

    target: ClientUpdatePushTarget
    messages: tuple[ClientUpdatePushMessage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.target, ClientUpdatePushTarget):
            raise TypeError("target 必须是 ClientUpdatePushTarget")
        normalized = tuple(self.messages)
        if any(
            not isinstance(message, ClientUpdatePushMessage) for message in normalized
        ):
            raise TypeError("messages 必须全部是 ClientUpdatePushMessage")
        object.__setattr__(self, "messages", normalized)


class ClientUpdatePushPort(Protocol):
    """客户端更新投递所需的最小端口。"""

    async def send(self, push: ClientUpdatePush) -> SenderResult:
        """向一个目标发送一轮消息；显式返回 False 表示失败。"""
        ...


class ClientUpdateDeliveryService:
    """按订阅筛选平台消息，并隔离每个目标的投递失败。"""

    def __init__(
        self,
        subscriptions: SubscriptionStore,
        push_port: ClientUpdatePushPort,
    ) -> None:
        self.subscriptions = subscriptions
        self.push_port = push_port

    async def deliver(self, changes: Sequence[ClientUpdateChange]) -> int:
        """向匹配订阅目标投递本轮变化，返回成功目标数。"""

        ordered_changes = _order_changes(changes)
        if not ordered_changes:
            return 0

        delivered = 0
        subscriptions = await self.subscriptions.get(
            messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE
        )
        for subscription in subscriptions:
            if not subscription.enabled:
                continue
            platforms = _subscription_platforms(subscription)
            if platforms is None:
                continue
            selected_changes = tuple(
                change for change in ordered_changes if change.platform in platforms
            )
            if not selected_changes:
                continue

            push = ClientUpdatePush(
                target=ClientUpdatePushTarget(
                    origin=subscription.unified_msg_origin,
                    bot_id=subscription.bot_id,
                ),
                messages=tuple(
                    ClientUpdatePushMessage(
                        platform=change.platform,
                        text=messages.format_change(change),
                    )
                    for change in selected_changes
                ),
            )
            try:
                result = await self.push_port.send(push)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "[dnaby][client_update] 订阅目标投递失败（错误类型：%s）",
                    type(error).__name__,
                )
                continue
            if result is False:
                logger.warning("[dnaby][client_update] 订阅目标投递返回失败")
                continue
            delivered += 1
        return delivered


class ClientUpdatePushAdapter:
    """把一轮 DTO 投递为普通消息或 OneBot 合并转发。"""

    def __init__(
        self,
        *,
        send_text: TextSender,
        send_forward: ForwardSender | None = None,
        merge_forward: bool = True,
    ) -> None:
        self._send_text = send_text
        self._send_forward = send_forward
        self.merge_forward = bool(merge_forward)

    async def send(self, push: ClientUpdatePush) -> bool:
        """按目标平台与配置选择合并转发，失败时降级为普通消息。"""

        if not push.messages:
            return True

        if (
            push.target.bot_id == "onebot"
            and self.merge_forward
            and len(push.messages) > 1
        ):
            if await self._try_send_forward(push):
                return True
        return await self._send_independent_text(push)

    async def _try_send_forward(self, push: ClientUpdatePush) -> bool:
        sender = self._send_forward
        if sender is None:
            logger.warning(
                "[dnaby][client_update] OneBot 合并转发不可用，原因：未提供转发适配器"
            )
            return False

        try:
            result = await sender(
                push.target.origin,
                tuple(message.text for message in push.messages),
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "[dnaby][client_update] OneBot 合并转发失败，降级普通消息（错误类型：%s）",
                type(error).__name__,
            )
            return False
        if result is False:
            logger.warning(
                "[dnaby][client_update] OneBot 合并转发返回失败，降级普通消息"
            )
            return False
        return True

    async def _send_independent_text(self, push: ClientUpdatePush) -> bool:
        success = True
        for message in push.messages:
            try:
                result = await self._send_text(push.target.origin, message.text)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "[dnaby][client_update] 普通消息投递失败，错误类型：%s",
                    type(error).__name__,
                )
                success = False
                continue
            if result is False:
                logger.warning("[dnaby][client_update] 普通消息投递返回失败")
                success = False
        return success


def _order_changes(
    changes: Sequence[ClientUpdateChange],
) -> tuple[ClientUpdateChange, ...]:
    normalized = tuple(changes)
    if any(not isinstance(change, ClientUpdateChange) for change in normalized):
        raise TypeError("changes 必须全部是 ClientUpdateChange")
    return tuple(
        sorted(
            normalized,
            key=lambda change: _CLIENT_PLATFORM_ORDER[change.platform],
        )
    )


def _subscription_platforms(
    subscription: Subscription,
) -> tuple[ClientPlatform, ...] | None:
    try:
        payload = json.loads(subscription.extra_data)
        if not isinstance(payload, dict):
            raise ValueError("订阅平台元数据必须是对象")
        raw_platforms = payload.get("platforms")
        if not isinstance(raw_platforms, list):
            raise ValueError("订阅平台元数据缺少 platforms 列表")
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
    "ClientUpdateDeliveryService",
    "ClientUpdatePush",
    "ClientUpdatePushAdapter",
    "ClientUpdatePushMessage",
    "ClientUpdatePushPort",
    "ClientUpdatePushTarget",
    "ForwardSender",
    "SenderResult",
    "TextSender",
]
