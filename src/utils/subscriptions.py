"""原生订阅存储：替代 gsucore ``gs_subscribe``。

- JSON 持久化到数据目录 ``subscriptions.json``。
- ``Subscription`` 记录推送目标（``unified_msg_origin``）与附加数据。
- 推送经 ``bind_push`` 注入的 ``context.send_message(umo, chain)`` 发送。

业务代码沿用 ``await gs_subscribe.get_subscribe/add_subscribe/...`` 写法。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .session import EventContext, Sender

PushFunc = Callable[[str, Any], Any]  # (unified_msg_origin, MessageChain) -> None

_push_func: PushFunc | None = None


def bind_push(fn: PushFunc) -> None:
    """注入推送函数（main.py initialize 时调用）。"""
    global _push_func
    _push_func = fn


@dataclass
class Subscription:
    type: str
    user_id: str = ""
    group_id: str = ""
    bot_id: str = ""
    bot_self_id: str = ""
    user_type: str = "group"  # "direct" | "group"
    unified_msg_origin: str = ""
    uid: str = ""
    extra_message: str = ""
    extra_data: str = ""

    async def send(self, msg: Any) -> None:
        """向订阅目标推送消息（text/bytes/PIL/list/segment）。"""
        from astrbot.core.message.message_event_result import MessageChain

        if _push_func is None:
            logger.warning(
                f"[订阅] 未绑定推送函数，跳过 {self.type} -> {self.unified_msg_origin}"
            )
            return
        sender = Sender(EventContext())
        sender.send(msg)
        chains = sender.to_chains()
        if not chains or not self.unified_msg_origin:
            return
        for chain in chains:
            await _push_func(self.unified_msg_origin, MessageChain(chain))


class SubscriptionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._subs: list[Subscription] = []
        self._lock = asyncio.Lock()
        self._loaded = False

    async def init(self, path: Path) -> None:
        """设置持久化路径并加载（main.py initialize 时调用）。"""
        self.path = path
        await self.load()

    # ---- 持久化 ----
    async def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._subs = [Subscription(**item) for item in data]
            except (OSError, json.JSONDecodeError, TypeError) as e:
                logger.error(f"[订阅] 加载失败: {e}")

    async def _save_unlocked(self) -> None:
        """在调用方已持有 ``_lock`` 时落盘，避免变更事务重复获取同一把锁。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([asdict(s) for s in self._subs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def save(self) -> None:
        async with self._lock:
            await self._save_unlocked()

    # ---- 查询 ----
    async def get_subscribe(
        self,
        boardcast_type: str,
        *,
        user_id: str | None = None,
        bot_id: str | None = None,
        user_type: str | None = None,
        uid: str | None = None,
        WS_BOT_ID: str | None = None,
    ) -> list[Subscription]:
        await self.load()
        result = []
        for sub in self._subs:
            if sub.type != boardcast_type:
                continue
            if user_id is not None and sub.user_id != user_id:
                continue
            if bot_id is not None and sub.bot_id != bot_id:
                continue
            if user_type is not None and sub.user_type != user_type:
                continue
            if uid is not None and sub.uid != uid:
                continue
            result.append(sub)
        return result

    # ---- 增删改 ----
    async def add_subscribe(
        self,
        area: str,
        boardcast_type: str,
        ev: EventContext,
        uid: str = "",
        extra_message: str = "",
        extra_data: str = "",
    ) -> None:
        async with self._lock:
            await self.load()
            sub = Subscription(
                type=boardcast_type,
                user_id=ev.user_id,
                group_id=ev.group_id or "",
                bot_id=ev.bot_id,
                bot_self_id=ev.bot_self_id(),
                user_type=ev.user_type,
                unified_msg_origin=ev.unified_msg_origin,
                uid=uid,
                extra_message=extra_message or "",
                extra_data=extra_data or "",
            )
            # 同一定向/会话 + 类型去重
            self._subs = [
                s
                for s in self._subs
                if not (
                    s.type == boardcast_type
                    and s.unified_msg_origin == sub.unified_msg_origin
                    and s.uid == sub.uid
                )
            ]
            self._subs.append(sub)
            await self._save_unlocked()

    async def delete_subscribe(
        self,
        area: str,
        boardcast_type: str,
        ev: EventContext,
        uid: str = "",
    ) -> None:
        async with self._lock:
            await self.load()
            self._subs = [
                s
                for s in self._subs
                if not (
                    s.type == boardcast_type
                    and s.unified_msg_origin == ev.unified_msg_origin
                    and s.uid == uid
                )
            ]
            await self._save_unlocked()

    async def update_subscribe_message(
        self,
        area: str,
        boardcast_type: str,
        ev: EventContext,
        uid: str = "",
        extra_message: str = "",
    ) -> None:
        async with self._lock:
            await self.load()
            for s in self._subs:
                if (
                    s.type == boardcast_type
                    and s.unified_msg_origin == ev.unified_msg_origin
                    and s.uid == uid
                ):
                    s.extra_message = extra_message
            await self._save_unlocked()

    async def update_subscribe_data(
        self,
        area: str,
        boardcast_type: str,
        ev: EventContext,
        extra_data: str = "",
        uid: str = "",
    ) -> None:
        async with self._lock:
            await self.load()
            for s in self._subs:
                if (
                    s.type == boardcast_type
                    and s.unified_msg_origin == ev.unified_msg_origin
                    and s.uid == uid
                ):
                    s.extra_data = extra_data
            await self._save_unlocked()


# 兼容业务代码的全局单例
gs_subscribe = SubscriptionStore(Path(""))
