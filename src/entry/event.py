"""事件入口边界。

框架事件只在 entry 层被读取。业务模块接收 EventActor 这样的值对象，
不会持有 AstrBot event，也不会依赖 legacy 事件适配类型。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from astrbot.api.message_components import At, AtAll, Reply

SCHEDULED_ACTOR_BOT_ID = "dnaby-scheduler"


@dataclass(frozen=True, slots=True)
class EventActor:
    """从 AstrBot 事件提取的最小调用者作用域。"""

    user_id: str
    bot_id: str
    group_id: str | None = None
    unified_msg_origin: str | None = None

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
        if self.unified_msg_origin is not None:
            origin = self.unified_msg_origin.strip()
            object.__setattr__(self, "unified_msg_origin", origin or None)


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
        unified_msg_origin=getattr(event, "unified_msg_origin", None),
    )


def target_user_from_event(
    event: Any,
    *,
    bot_id: str | None = None,
) -> str | None:
    """从 AstrBot 公开消息链提取最后一个有效 @ 用户。"""

    get_messages = getattr(event, "get_messages", None)
    if not callable(get_messages):
        return None
    messages = get_messages()
    if not isinstance(messages, Iterable):
        return None
    normalized_bot_id = str(bot_id).strip() if bot_id is not None else None
    target_user_id: str | None = None
    for component in messages:
        if isinstance(component, AtAll) or not isinstance(component, At):
            continue
        raw_target = getattr(component, "qq", None)
        if raw_target is None:
            continue
        candidate = str(raw_target).strip()
        if (
            not candidate
            or candidate.lower() == "all"
            or candidate == normalized_bot_id
        ):
            continue
        target_user_id = candidate
    return target_user_id


def images_from_event(event: Any) -> tuple[str, ...]:
    """从 AstrBot 公开消息链提取图片载荷（本地路径 / base64 / URL）。"""

    from urllib.parse import unquote, urlparse

    from astrbot.api.message_components import Image

    get_messages = getattr(event, "get_messages", None)
    if not callable(get_messages):
        return ()
    messages = get_messages()
    if not isinstance(messages, Iterable):
        return ()
    sources: list[str] = []
    for component in messages:
        if not isinstance(component, Image):
            continue
        file_value = str(getattr(component, "file", "") or "")
        if file_value.startswith("base64://"):
            sources.append(file_value)
        elif file_value.startswith("file:"):
            sources.append(unquote(urlparse(file_value).path))
        elif file_value.startswith(("http://", "https://")):
            sources.append(file_value)
        else:
            path = str(getattr(component, "path", "") or "")
            if path:
                sources.append(path)
    return tuple(sources)


def reply_id_from_event(event: Any) -> str | None:
    """从 AstrBot 公共消息链提取第一条 Reply 的平台消息 ID。"""

    get_messages = getattr(event, "get_messages", None)
    if not callable(get_messages):
        return None
    messages = get_messages()
    if not isinstance(messages, Iterable):
        return None
    for component in messages:
        if not isinstance(component, Reply):
            continue
        reply_id = str(component.id).strip()
        return reply_id or None
    return None


class EventEntryPoint(Protocol):
    """业务事件入口的最小公共协议。"""

    async def handle(self, event: Any) -> None:
        """处理一个 AstrBot 事件。"""


class EmptyEventEntryPoint:
    """没有命令注册时使用的显式空入口。"""

    async def handle(self, event: Any) -> None:
        """v0.1 没有可处理的命令，故不产生框架响应。"""
