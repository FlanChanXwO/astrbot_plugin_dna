"""框架无关的订阅存储。

替代旧 ``dnaby/utils/subscriptions.py`` 与 gsucore ``gs_subscribe``：以 JSON 持久化
到运行期数据目录，按 ``type`` + ``unified_msg_origin``（+ 个人作用域的 ``uid`` 语义
字段）去重。业务层只读写 ``Subscription`` 值对象，推送目标统一由
``unified_msg_origin`` 表示，发送动作由调用方（scheduler/bootstrap）注入，本模块不
接触 AstrBot 事件或消息段。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Subscription:
    """一条推送订阅；origin 标识平台会话。"""

    type: str
    unified_msg_origin: str
    user_id: str = ""
    group_id: str = ""
    bot_id: str = ""
    user_type: str = "group"
    uid: str = ""
    extra_message: str = ""
    extra_data: str = ""


class SubscriptionStore:
    """订阅的读写入口；写操作在进程内锁内完成并原子落盘。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._subs: list[Subscription] = []
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        """幂等加载既有 JSON；损坏数据显式失败，不静默清空。"""

        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise TypeError("subscription file must be a list")
            self._subs = [
                Subscription(
                    type=str(item["type"]),
                    unified_msg_origin=str(item["unified_msg_origin"]),
                    user_id=str(item.get("user_id", "")),
                    group_id=str(item.get("group_id", "")),
                    bot_id=str(item.get("bot_id", "")),
                    user_type=str(item.get("user_type", "group")),
                    uid=str(item.get("uid", "")),
                    extra_message=str(item.get("extra_message", "")),
                    extra_data=str(item.get("extra_data", "")),
                )
                for item in raw
                if isinstance(item, dict) and item.get("type") and item.get("unified_msg_origin")
            ]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            self._subs = []
            raise RuntimeError(
                f"订阅文件损坏: {self.path.name} ({type(error).__name__})"
            ) from error

    def _save_unlocked(self) -> None:
        """调用方已持有 ``_lock`` 时原子写盘。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([asdict(sub) for sub in self._subs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def add(
        self,
        sub_type: str,
        *,
        origin: str,
        user_id: str = "",
        group_id: str = "",
        bot_id: str = "",
        user_type: str = "group",
        uid: str = "",
        extra_message: str = "",
        extra_data: str = "",
    ) -> Subscription:
        """新增订阅；同一 type+origin+uid 只保留最新一条。

        个人作用域订阅（如密函）以 ``uid`` 区分同会话内不同用户的记录，避免互相覆盖；
        会话级订阅（图片/文本/公告/签到结果）不传 uid，退化为 type+origin 去重。
        """

        async with self._lock:
            await self.load()
            subscription = Subscription(
                type=sub_type,
                unified_msg_origin=origin,
                user_id=user_id,
                group_id=group_id,
                bot_id=bot_id,
                user_type=user_type,
                uid=uid,
                extra_message=extra_message,
                extra_data=extra_data,
            )
            self._subs = [
                sub
                for sub in self._subs
                if not (
                    sub.type == sub_type
                    and sub.unified_msg_origin == origin
                    and sub.uid == uid
                )
            ]
            self._subs.append(subscription)
            self._save_unlocked()
        return subscription

    async def delete(
        self,
        sub_type: str,
        origin: str,
        uid: str = "",
    ) -> bool:
        """删除一条订阅（type+origin+uid 精确匹配）；返回是否命中。"""

        async with self._lock:
            await self.load()
            remaining = [
                sub
                for sub in self._subs
                if not (
                    sub.type == sub_type
                    and sub.unified_msg_origin == origin
                    and sub.uid == uid
                )
            ]
            if len(remaining) == len(self._subs):
                return False
            self._subs = remaining
            self._save_unlocked()
            return True

    async def delete_personal_subscriptions(
        self,
        user_id: str,
        *,
        subscription_type: str,
    ) -> int:
        """删除指定用户的个人订阅类型，保留群级/会话级订阅。

        个人密函记录以 ``uid=user_id`` 标识；群级订阅没有该个人 UID。内存快照
        只有在 JSON 原子写成功后才提交，写盘失败时恢复原列表，保证协调器可重试。
        """

        async with self._lock:
            await self.load()
            previous = self._subs
            remaining = [
                sub
                for sub in previous
                if not (
                    sub.type == subscription_type
                    and sub.user_id == user_id
                    and sub.uid == user_id
                )
            ]
            deleted = len(previous) - len(remaining)
            if deleted == 0:
                return 0
            self._subs = remaining
            try:
                self._save_unlocked()
            except BaseException:
                self._subs = previous
                raise
            return deleted

    async def update(
        self,
        sub_type: str,
        origin: str,
        *,
        uid: str = "",
        extra_message: str | None = None,
        extra_data: str | None = None,
    ) -> bool:
        """更新一条订阅（type+origin+uid 精确匹配）的附加数据；返回是否命中。"""

        async with self._lock:
            await self.load()
            target = next(
                (
                    sub
                    for sub in self._subs
                    if (
                        sub.type == sub_type
                        and sub.unified_msg_origin == origin
                        and sub.uid == uid
                    )
                ),
                None,
            )
            if target is None:
                return False
            self._subs = [
                Subscription(
                    type=sub.type,
                    unified_msg_origin=sub.unified_msg_origin,
                    user_id=sub.user_id,
                    group_id=sub.group_id,
                    bot_id=sub.bot_id,
                    user_type=sub.user_type,
                    uid=sub.uid,
                    extra_message=extra_message if extra_message is not None else sub.extra_message,
                    extra_data=extra_data if extra_data is not None else sub.extra_data,
                )
                if (
                    sub.type == sub_type
                    and sub.unified_msg_origin == origin
                    and sub.uid == uid
                )
                else sub
                for sub in self._subs
            ]
            self._save_unlocked()
            return True

    async def get(
        self,
        sub_type: str,
        *,
        user_id: str | None = None,
        bot_id: str | None = None,
        group_id: str | None = None,
        user_type: str | None = None,
        uid: str | None = None,
    ) -> tuple[Subscription, ...]:
        """按订阅类型返回目标，支持个人/群组作用域过滤。"""

        await self.load()
        result = []
        for sub in self._subs:
            if sub.type != sub_type:
                continue
            if user_id is not None and sub.user_id != user_id:
                continue
            if bot_id is not None and sub.bot_id != bot_id:
                continue
            if group_id is not None and sub.group_id != group_id:
                continue
            if user_type is not None and sub.user_type != user_type:
                continue
            if uid is not None and sub.uid != uid:
                continue
            result.append(sub)
        return tuple(result)

    async def list_all(self) -> tuple[Subscription, ...]:
        """返回全部订阅（供生命周期清理与测试核对）。"""

        await self.load()
        return tuple(self._subs)


__all__ = ["Subscription", "SubscriptionStore"]
