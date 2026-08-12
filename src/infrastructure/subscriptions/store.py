"""框架无关的订阅存储。

替代旧 ``dnaby/utils/subscriptions.py`` 与 gsucore ``gs_subscribe``：以 JSON 持久化
到运行期数据目录，按 ``type`` + ``unified_msg_origin`` 去重。业务层只读写
``Subscription`` 值对象，推送目标统一由 ``unified_msg_origin`` 表示，发送动作由
调用方（scheduler/bootstrap）注入，本模块不接触 AstrBot 事件或消息段。
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


class SubscriptionStore:
    """订阅的读写入口；写操作在进程内锁内完成并原子落盘。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._subs: list[Subscription] = []
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        """幂等加载既有 JSON；损坏数据按空订阅处理，不抛出。"""

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
    ) -> Subscription:
        """新增订阅；同一 type+origin 只保留最新一条。"""

        async with self._lock:
            await self.load()
            subscription = Subscription(
                type=sub_type,
                unified_msg_origin=origin,
                user_id=user_id,
                group_id=group_id,
                bot_id=bot_id,
                user_type=user_type,
            )
            self._subs = [
                sub
                for sub in self._subs
                if not (sub.type == sub_type and sub.unified_msg_origin == origin)
            ]
            self._subs.append(subscription)
            self._save_unlocked()
        return subscription

    async def delete(self, sub_type: str, origin: str) -> bool:
        """删除一条订阅；返回是否命中。"""

        async with self._lock:
            await self.load()
            remaining = [
                sub
                for sub in self._subs
                if not (sub.type == sub_type and sub.unified_msg_origin == origin)
            ]
            if len(remaining) == len(self._subs):
                return False
            self._subs = remaining
            self._save_unlocked()
            return True

    async def get(self, sub_type: str) -> tuple[Subscription, ...]:
        """按订阅类型返回全部目标。"""

        await self.load()
        return tuple(sub for sub in self._subs if sub.type == sub_type)

    async def list_all(self) -> tuple[Subscription, ...]:
        """返回全部订阅（供生命周期清理与测试核对）。"""

        await self.load()
        return tuple(self._subs)


__all__ = ["Subscription", "SubscriptionStore"]
