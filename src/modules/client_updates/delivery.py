"""客户端更新的框架无关 Source 推送 DTO 与注入式投递适配器。

领域层只负责把事件创建时固定的 Target 消息交给最小化推送端口。OneBot 节点
的具体构造留在注入的 ``send_forward`` 回调中；这里不导入 AstrBot 消息组件，
避免客户端更新 use case 与宿主框架耦合。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from . import messages
from .contracts import ClientUpdateChange
from .registry import CLIENT_UPDATE_REGISTRY, resolve_client_update_target
from .routing import active_subscriptions as _active_subscriptions
from .state import (
    ClientUpdatePendingEvent,
    ClientUpdatePendingTarget,
    ClientUpdateStateStore,
    canonicalize_client_update_change,
)

logger = logging.getLogger(__name__)

_CLIENT_SOURCE_ORDER = {
    source.source_id: index
    for index, source in enumerate(CLIENT_UPDATE_REGISTRY.sources)
}
_ONEBOT_PLATFORM_NAMES = frozenset(("aiocqhttp", "onebot"))

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
    """一个 Source 变化及其固定 Target 集合对应的用户可见消息。"""

    source_id: str
    target_ids: tuple[str, ...]
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id 必须是非空字符串")
        normalized_target_ids = tuple(self.target_ids)
        if not normalized_target_ids:
            raise ValueError("target_ids 必须至少包含一个 Target ID")
        if len(normalized_target_ids) != len(set(normalized_target_ids)):
            raise ValueError("target_ids 不能重复")
        for target_id in normalized_target_ids:
            target = resolve_client_update_target(target_id)
            if target.source_id != self.source_id:
                raise ValueError("消息 Target 与 Source 不一致")
        if not isinstance(self.text, str):
            raise TypeError("text 必须是字符串")
        object.__setattr__(self, "target_ids", normalized_target_ids)


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
    """按有效订阅投递 Source 消息，并隔离每个目标的投递失败。

    未注入 ``state`` 时，``deliver`` 保留框架无关 DTO seam 的即时投递语义，
    供单元测试和其他调用方构造消息。bootstrap 会注入状态 store，此时每轮
    投递都会先重试持久化 pending 事件，再为当前变化固定首次目标并投递。
    """

    def __init__(
        self,
        subscriptions: SubscriptionStore,
        push_port: ClientUpdatePushPort,
        *,
        state: ClientUpdateStateStore | None = None,
    ) -> None:
        self.subscriptions = subscriptions
        self.push_port = push_port
        self.state = state

    async def deliver(self, changes: Sequence[ClientUpdateChange]) -> int:
        """投递变化；有状态运行时先重试 pending 事件。"""

        if self.state is None:
            return await self._deliver_without_state(changes)
        return await self._deliver_with_state(changes)

    async def _deliver_without_state(
        self,
        changes: Sequence[ClientUpdateChange],
    ) -> int:
        """直接投递 DTO seam，不创建持久化事件。"""

        ordered_changes = _order_changes(changes)
        if not ordered_changes:
            return 0

        delivered = 0
        subscriptions = await self._subscriptions()
        active = _active_subscriptions(subscriptions)
        for subscription, routable in active.values():
            if not routable:
                continue
            push = _build_push(
                ClientUpdatePushTarget(
                    origin=subscription.unified_msg_origin,
                    bot_id=subscription.bot_id,
                ),
                ordered_changes,
            )
            if await self._send_push(push):
                delivered += 1
        return delivered

    async def _deliver_with_state(
        self,
        changes: Sequence[ClientUpdateChange],
    ) -> int:
        """按固定目标集合投递，并在每个目标成功后更新状态。"""

        state = self.state
        if state is None:
            raise RuntimeError("client update delivery state unavailable")

        ordered_changes = _order_changes(changes)
        pending_keys_before = {
            event.event_key for event in await state.pending_events()
        }
        delivered = await self._deliver_pending_events()
        pending_keys = {event.event_key for event in await state.pending_events()}
        if not ordered_changes:
            return delivered

        active = _active_subscriptions(await self._subscriptions())
        new_events: list[ClientUpdatePendingEvent] = []
        new_event_keys = set(pending_keys)
        for change in ordered_changes:
            if change.event_key in pending_keys_before:
                # pending-first 已尝试过这个事件；无论成功清理还是失败保留，
                # 当前轮询结果都不能再次创建它，否则成功路径会重复推送。
                continue
            targets = tuple(
                ClientUpdatePendingTarget(
                    origin=subscription.unified_msg_origin,
                    uid=subscription.uid,
                    bot_id=subscription.bot_id,
                    target_ids=change.target_ids,
                )
                for subscription, routable in active.values()
                if routable
            )
            event = await state.ensure_pending_event(change, targets)
            if event is not None and event.event_key not in new_event_keys:
                new_events.append(event)
                new_event_keys.add(event.event_key)
        return delivered + await self._deliver_event_groups(
            _group_pending_events(new_events)
        )

    async def _deliver_pending_events(self) -> int:
        state = self.state
        if state is None:
            raise RuntimeError("client update delivery state unavailable")

        events = await state.pending_events()
        if not events:
            return 0
        active = _active_subscriptions(await self._subscriptions())
        groups: dict[
            tuple[str, str, str],
            tuple[ClientUpdatePendingTarget, list[ClientUpdatePendingEvent]],
        ] = {}
        for event in events:
            for target in event.pending_targets:
                active_entry = active.get(target.key)
                if active_entry is None:
                    await state.remove_event_target(event.event_key, target)
                    continue
                _subscription, routable = active_entry
                if not routable:
                    await state.remove_event_target(event.event_key, target)
                    continue
                group_key = (target.origin, target.uid, target.bot_id)
                group = groups.get(group_key)
                if group is None:
                    groups[group_key] = (target, [event])
                else:
                    group[1].append(event)
        return await self._deliver_event_groups(tuple(groups.values()))

    async def _deliver_event_groups(
        self,
        groups: Sequence[
            tuple[ClientUpdatePendingTarget, list[ClientUpdatePendingEvent]]
        ],
    ) -> int:
        """按目标合并同批事件，并逐事件标记成功。"""

        state = self.state
        if state is None:
            raise RuntimeError("client update delivery state unavailable")

        delivered = 0
        for target, pending_events in groups:
            push = _build_push(
                ClientUpdatePushTarget(origin=target.origin, bot_id=target.bot_id),
                tuple(event.change for event in pending_events),
            )
            if not await self._send_push(push):
                continue
            delivered += 1
            for event in pending_events:
                await state.mark_delivered(event.event_key, target)
        return delivered

    async def _subscriptions(self) -> tuple[Subscription, ...]:
        return await self.subscriptions.get(messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE)

    async def _send_push(self, push: ClientUpdatePush) -> bool:
        try:
            result = await self.push_port.send(push)
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "[dnaby][client_update] 订阅目标投递失败（错误类型：%s）",
                type(error).__name__,
            )
            return False
        if result is False:
            logger.warning("[dnaby][client_update] 订阅目标投递返回失败")
            return False
        return True


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
        """按目标适配器与配置选择合并转发，失败时降级为普通消息。"""

        if not push.messages:
            return True

        if (
            _is_onebot_target(push.target)
            and self.merge_forward
            and len(push.messages) > 1
            and await self._try_send_forward(push)
        ):
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


def _build_push(
    target: ClientUpdatePushTarget,
    changes: Sequence[ClientUpdateChange],
) -> ClientUpdatePush:
    return ClientUpdatePush(
        target=target,
        messages=tuple(
            ClientUpdatePushMessage(
                source_id=change.source_id,
                target_ids=change.target_ids,
                text=messages.format_change(change),
            )
            for change in changes
        ),
    )


def _group_pending_events(
    events: Sequence[ClientUpdatePendingEvent],
) -> tuple[tuple[ClientUpdatePendingTarget, list[ClientUpdatePendingEvent]], ...]:
    groups: dict[
        tuple[str, str, str],
        tuple[ClientUpdatePendingTarget, list[ClientUpdatePendingEvent]],
    ] = {}
    for event in events:
        for target in event.pending_targets:
            group_key = (target.origin, target.uid, target.bot_id)
            group = groups.get(group_key)
            if group is None:
                groups[group_key] = (target, [event])
            else:
                group[1].append(event)
    return tuple(groups.values())


def _is_onebot_target(target: ClientUpdatePushTarget) -> bool:
    """使用 AstrBot 的 origin 平台段识别 OneBot，避免把 self_id 当平台名。"""

    platform_name = target.origin.split(":", 1)[0]
    return target.bot_id == "onebot" or platform_name in _ONEBOT_PLATFORM_NAMES


def _order_changes(
    changes: Sequence[ClientUpdateChange],
) -> tuple[ClientUpdateChange, ...]:
    normalized = tuple(
        canonicalize_client_update_change(change) for change in tuple(changes)
    )
    return tuple(
        sorted(
            normalized,
            key=lambda change: _CLIENT_SOURCE_ORDER[change.source_id],
        )
    )


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
