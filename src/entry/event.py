"""事件入口边界。

框架事件只在 entry 层被读取。业务模块接收 EventActor 这样的值对象，
不会持有 AstrBot event，也不会依赖 legacy Sender/EventContext。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EventActor:
    """从 AstrBot 事件提取的最小调用者作用域。"""

    user_id: str
    bot_id: str
    group_id: str | None = None

    def __post_init__(self) -> None:
        """拒绝无法定位账号数据的空作用域。"""

        user_id = self.user_id.strip()
        bot_id = self.bot_id.strip()
        if not user_id or not bot_id:
            raise ValueError("事件缺少 user_id 或 bot_id")
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "bot_id", bot_id)
        if self.group_id is not None:
            group_id = self.group_id.strip()
            object.__setattr__(self, "group_id", group_id or None)


def actor_from_event(event: Any) -> EventActor | None:
    """使用 AstrBot 公开事件方法提取调用者；不猜测 fixture 的隐式字段。"""

    get_sender_id = getattr(event, "get_sender_id", None)
    get_self_id = getattr(event, "get_self_id", None)
    if not callable(get_sender_id) or not callable(get_self_id):
        return None

    user_id = get_sender_id()
    bot_id = get_self_id()
    if user_id is None or bot_id is None:
        return None

    get_group_id = getattr(event, "get_group_id", None)
    group_id = get_group_id() if callable(get_group_id) else None
    return EventActor(
        user_id=str(user_id),
        bot_id=str(bot_id),
        group_id=None if group_id is None else str(group_id),
    )


class EventEntryPoint(Protocol):
    """业务事件入口的最小公共协议。"""

    async def handle(self, event: Any) -> None:
        """处理一个 AstrBot 事件。"""


class EmptyEventEntryPoint:
    """没有命令注册时使用的显式空入口。"""

    async def handle(self, event: Any) -> None:
        """v0.1 没有可处理的命令，故不产生框架响应。"""
