"""Handle repeated subscription send failures without deleting healthy groups."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from ..infrastructure.logger import logger
from ..infrastructure.subscriptions.store import SubscriptionStore
from .client_updates.state import ClientUpdateStateStore
from .notices.ann_delivery_state import AnnDeliveryStateStore

GroupKey = tuple[str, str]
MembershipProbe = Callable[[str, str], Awaitable[bool | None]]


def group_key(origin: str) -> GroupKey | None:
    """Normalize Telegram topic sessions to their parent group."""

    parts = origin.split(":", 2)
    if len(parts) != 3 or parts[1] != "GroupMessage":
        return None
    group_id = parts[2].split("#", 1)[0]
    return (parts[0], group_id) if parts[0] and group_id else None


class GroupSubscriptionHealth:
    """Prune all subscriptions only when a platform confirms group loss."""

    def __init__(
        self,
        subscriptions: SubscriptionStore,
        announcements: AnnDeliveryStateStore,
        client_updates: ClientUpdateStateStore,
        probe: MembershipProbe,
        *,
        failure_threshold: int = 5,
        retry_delay_seconds: float = 300,
    ) -> None:
        self.subscriptions = subscriptions
        self.announcements = announcements
        self.client_updates = client_updates
        self.probe = probe
        self.failure_threshold = failure_threshold
        self.retry_delay_seconds = retry_delay_seconds
        self._failures: dict[str, int] = {}
        self._defer_until: dict[str, float] = {}
        self._removed_until: dict[GroupKey, float] = {}
        self._checking: set[GroupKey] = set()
        self._lock = asyncio.Lock()

    def should_skip(self, origin: str) -> bool:
        key = group_key(origin)
        now = monotonic()
        return bool(
            key is not None
            and (
                self._removed_until.get(key, 0) > now
                or self._defer_until.get(origin, 0) > now
            )
        )

    async def record(self, origin: str, succeeded: bool) -> None:
        key = group_key(origin)
        if key is None:
            return
        async with self._lock:
            if succeeded:
                self._failures.pop(origin, None)
                self._defer_until.pop(origin, None)
                return
            if self.should_skip(origin) or key in self._checking:
                return
            count = self._failures.get(origin, 0) + 1
            self._failures[origin] = count
            if count < self.failure_threshold:
                return
            self._checking.add(key)

        try:
            membership = await asyncio.wait_for(self.probe(*key), timeout=10)
            if membership is False:
                removed = await self._remove_group(key)
                self._removed_until[key] = monotonic() + self.retry_delay_seconds
                logger.warning(
                    "已确认群不可访问，清理全部 DNA 订阅 platform=%s group=%s subscriptions=%s",
                    key[0],
                    key[1],
                    removed,
                )
            else:
                # Network/media errors and unsupported platforms must not erase data.
                self._defer_until[origin] = monotonic() + self.retry_delay_seconds
                logger.warning(
                    "群消息连续失败，暂缓重试 platform=%s group=%s membership=%s",
                    key[0],
                    key[1],
                    "present" if membership is True else "unknown",
                )
        except Exception as error:  # noqa: BLE001 - Keep subscriptions if cleanup fails.
            self._defer_until[origin] = monotonic() + self.retry_delay_seconds
            logger.warning(
                "检查群订阅失败 platform=%s group=%s error_type=%s",
                key[0],
                key[1],
                type(error).__name__,
            )
        finally:
            async with self._lock:
                self._failures.pop(origin, None)
                self._checking.discard(key)

    async def _remove_group(self, key: GroupKey) -> int:
        subscribed = await self.subscriptions.list_all()
        stale = [sub for sub in subscribed if group_key(sub.unified_msg_origin) == key]
        for sub in stale:
            await self.subscriptions.delete(
                sub.type, sub.unified_msg_origin, uid=sub.uid
            )

        records = await self.announcements.records()
        ann_origins = {
            origin
            for record in records.values()
            for origin in record.observed_targets | record.delivered_targets
            if group_key(origin) == key
        }
        for origin in ann_origins:
            await self.announcements.remove_target(origin)

        events = await self.client_updates.pending_events()
        client_targets = {
            (target.origin, target.uid)
            for event in events
            for target in event.targets
            if group_key(target.origin) == key
        }
        for origin, uid in client_targets:
            await self.client_updates.remove_target(origin, uid=uid)
        return len(stale)
