"""公告订阅目标生命周期协调器。

公告目标只能由真实群聊订阅命令发现；本服务统一负责订阅、退订、启停和删除，
并协调投递状态，避免聊天命令与 Dashboard 各自维护不同状态机。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from . import messages
from .ann_delivery_state import AnnDeliveryStateStore


class AnnouncementListSource(Protocol):
    async def current_announcement_ids(self) -> tuple[str, ...]: ...


class TargetMutationStatus(StrEnum):
    APPLIED = "applied"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class TargetMutationResult:
    """目标生命周期动作的结构化结果。"""

    status: TargetMutationStatus
    subscription: Subscription | None = None
    message: str = ""


def encode_target_id(subscription: Subscription) -> str:
    payload = json.dumps(
        [subscription.type, subscription.unified_msg_origin, subscription.uid],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_target_id(value: object) -> tuple[str, str, str] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, binascii.Error):
        return None
    if (
        not isinstance(payload, list)
        or len(payload) != 3
        or any(not isinstance(item, str) for item in payload)
        or not payload[0]
        or not payload[1]
    ):
        return None
    key = (payload[0], payload[1], payload[2])
    if (
        encode_target_id(
            Subscription(type=key[0], unified_msg_origin=key[1], uid=key[2])
        )
        != value
    ):
        return None
    return key


class AnnouncementTargetService:
    """公告目标唯一生命周期入口。"""

    def __init__(
        self,
        subscriptions: SubscriptionStore,
        delivery_state: AnnDeliveryStateStore,
        announcement_source: AnnouncementListSource,
    ) -> None:
        self.subscriptions = subscriptions
        self.delivery_state = delivery_state
        self.announcement_source = announcement_source
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _lock_for(self, key: tuple[str, str, str]) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    async def _find(self, key: tuple[str, str, str]) -> Subscription | None:
        sub_type, origin, uid = key
        return next(
            (
                item
                for item in await self.subscriptions.list_all()
                if item.type == sub_type
                and item.unified_msg_origin == origin
                and item.uid == uid
            ),
            None,
        )

    async def subscribe(
        self,
        *,
        origin: str,
        group_id: str,
        bot_id: str,
        user_id: str = "",
    ) -> TargetMutationResult:
        if not origin or not group_id or not bot_id:
            return TargetMutationResult(
                TargetMutationStatus.INVALID, message="公告目标身份不完整"
            )
        subscription = await self.subscriptions.add(
            messages.ANN_SUBSCRIBE,
            origin=origin,
            user_id=user_id,
            group_id=group_id,
            bot_id=bot_id,
            user_type="group",
            enabled=True,
            provenance="chat_command",
        )
        return TargetMutationResult(
            TargetMutationStatus.APPLIED, subscription=subscription
        )

    async def unsubscribe(self, target_id: str) -> TargetMutationResult:
        return await self.delete(target_id)

    async def disable(self, target_id: str) -> TargetMutationResult:
        key = decode_target_id(target_id)
        if key is None:
            return TargetMutationResult(
                TargetMutationStatus.INVALID, message="target_id 无效"
            )
        async with self._lock_for(key):
            target = await self._find(key)
            if target is None:
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            if not await self.subscriptions.update(
                key[0], key[1], uid=key[2], enabled=False
            ):
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            disabled = replace(target, enabled=False)
            try:
                await self.delivery_state.remove_target(target.unified_msg_origin)
            except Exception as error:  # noqa: BLE001
                return TargetMutationResult(
                    TargetMutationStatus.PARTIAL,
                    subscription=disabled,
                    message=f"目标已停用，但投递状态清理失败: {type(error).__name__}",
                )
            return TargetMutationResult(
                TargetMutationStatus.APPLIED, subscription=disabled
            )

    async def enable(self, target_id: str) -> TargetMutationResult:
        key = decode_target_id(target_id)
        if key is None:
            return TargetMutationResult(
                TargetMutationStatus.INVALID, message="target_id 无效"
            )
        async with self._lock_for(key):
            target = await self._find(key)
            if target is None:
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            try:
                ids = await self.announcement_source.current_announcement_ids()
                await self.delivery_state.baseline_target(
                    target.unified_msg_origin, ids
                )
            except Exception as error:  # noqa: BLE001
                return TargetMutationResult(
                    TargetMutationStatus.PARTIAL,
                    subscription=target,
                    message=f"公告基线建立失败，目标仍保持停用: {type(error).__name__}",
                )
            if not await self.subscriptions.update(
                key[0], key[1], uid=key[2], enabled=True
            ):
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            return TargetMutationResult(
                TargetMutationStatus.APPLIED,
                subscription=replace(target, enabled=True),
            )

    async def delete(self, target_id: str) -> TargetMutationResult:
        key = decode_target_id(target_id)
        if key is None:
            return TargetMutationResult(
                TargetMutationStatus.INVALID, message="target_id 无效"
            )
        async with self._lock_for(key):
            target = await self._find(key)
            if target is None:
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            if not await self.subscriptions.delete(*key):
                return TargetMutationResult(
                    TargetMutationStatus.NOT_FOUND, message="公告目标不存在"
                )
            try:
                await self.delivery_state.remove_target(target.unified_msg_origin)
            except Exception as error:  # noqa: BLE001
                return TargetMutationResult(
                    TargetMutationStatus.PARTIAL,
                    subscription=target,
                    message=f"目标已删除，但投递状态清理失败: {type(error).__name__}",
                )
            return TargetMutationResult(
                TargetMutationStatus.APPLIED, subscription=target
            )
