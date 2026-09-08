"""事件入口边界。

框架事件只在 entry 层被读取。业务模块接收 EventActor 这样的值对象，
不会持有 AstrBot event，也不会依赖 legacy 事件适配类型。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from astrbot.api.message_components import At, AtAll, Plain, Reply

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


_INLINE_MENTION_RE = re.compile(r"<@!?([^>\s]+)>")
_ONEBOT_DISPLAY_MENTION_RE = re.compile(r"\s*@(?P<name>[^\r\n]*?)\s*\((?P<qq>\d+)\)\s*")
_ONEBOT_BARE_MENTION_SUFFIX_RE = re.compile(r"\s*@(?P<name>(?!\d+\s*$)[^\r\n]+?)\s*$")


@dataclass(frozen=True, slots=True)
class MentionTargetResult:
    """消息链中 @ 目标的解析结果。"""

    target_user_id: str | None
    has_unresolved_mention: bool


def _inline_mention_targets(text: object) -> tuple[str, ...]:
    """提取平台常见的 ``<@id>`` / ``<@!id>`` 传输标记。"""

    if not isinstance(text, str):
        return ()
    return tuple(
        target.strip() for target in _INLINE_MENTION_RE.findall(text) if target.strip()
    )


def _onebot_display_mention_targets(text: object) -> tuple[str, ...]:
    """提取 OneBot 将 At 展示为 ``@昵称(qq)`` 时携带的 QQ 号。"""

    if not isinstance(text, str):
        return ()
    return tuple(
        match.group("qq")
        for match in _ONEBOT_DISPLAY_MENTION_RE.finditer(text)
        if match.group("qq").strip()
    )


def _has_unresolved_onebot_display_mention(text: object) -> bool:
    """识别缺少 QQ 号的 OneBot @ 展示，避免静默退回调用者。"""

    if not isinstance(text, str):
        return False
    normalized = _INLINE_MENTION_RE.sub(" ", text)
    normalized = _ONEBOT_DISPLAY_MENTION_RE.sub(" ", normalized)
    return _ONEBOT_BARE_MENTION_SUFFIX_RE.search(normalized) is not None


def _strip_inline_mentions(text: object) -> str:
    """移除平台 @ 标记，保留真正的命令文本和普通 ``@123`` 文本。"""

    normalized = _INLINE_MENTION_RE.sub(" ", str(text or ""))
    normalized = _ONEBOT_DISPLAY_MENTION_RE.sub(" ", normalized)
    return _ONEBOT_BARE_MENTION_SUFFIX_RE.sub(" ", normalized).strip()


def _is_ignored_mention_target(
    candidate: str,
    normalized_bot_id: str | None,
) -> bool:
    """判断目标是否代表全体或机器人自身，而不是外部查询目标。"""

    return candidate.lower() == "all" or (
        normalized_bot_id is not None and candidate == normalized_bot_id
    )


def command_text_from_event(event: Any) -> str:
    """从真实 AstrBot 消息链提取纯文本命令，忽略 At、回复和图片。

    消息链可将 At 放在命令前或后；只拼接 Plain 组件，避免把展示字符串中的
    ``@用户``、``[回复]`` 等平台标记误交给正则解析。部分平台会把 @ 目标保留为
    ``<@id>`` 或 ``<@!id>`` 的纯文本传输标记，这里同样移除。没有可用消息链时
    回退到 AstrBot 的 ``get_message_str()``，兼容旧 fixture 和非标准事件。
    """

    get_messages = getattr(event, "get_messages", None)
    if callable(get_messages):
        messages = get_messages()
        if isinstance(messages, Iterable):
            text = "".join(
                _strip_inline_mentions(getattr(component, "text", "") or "")
                for component in messages
                if isinstance(component, Plain)
            ).strip()
            if text:
                return text

    get_message_str = getattr(event, "get_message_str", None)
    if callable(get_message_str):
        return _strip_inline_mentions(get_message_str())
    return ""


def _raw_onebot_mention_targets(event: Any) -> tuple[object, ...]:
    """从 AstrBot 消息对象公开的 OneBot 原始消息段恢复 At 目标。"""

    message_obj = getattr(event, "message_obj", None)
    raw_message = getattr(message_obj, "raw_message", None)
    if not isinstance(raw_message, Mapping):
        return ()
    segments = raw_message.get("message")
    if not isinstance(segments, Iterable):
        return ()
    targets: list[object] = []
    for segment in segments:
        if not isinstance(segment, Mapping) or segment.get("type") != "at":
            continue
        data = segment.get("data")
        targets.append(data.get("qq") if isinstance(data, Mapping) else None)
    return tuple(targets)


def mention_target_from_event(
    event: Any,
    *,
    bot_id: str | None = None,
) -> MentionTargetResult:
    """解析消息链中的 @ 目标，并区分“没有 @”与“@ 无法解析”。

    真实 AstrBot 消息链优先使用 ``At`` 组件；若适配器把目标保留为
    ``<@id>`` / ``<@!id>`` 纯文本，则按同一传输标记解析。OneBot 适配器在
    成员信息请求失败时可能只保留公开的原始消息段，这里也从 ``raw_message``
    恢复目标。机器人自身的 @ 是命令唤醒，不视为查询目标；全体、空目标等无效
    @ 会标记为未解析，交由命令入口发出明确提示，避免静默回退为查询调用者。
    """

    normalized_bot_id = str(bot_id).strip() if bot_id is not None else None
    target_user_id: str | None = None
    has_non_bot_mention = False
    has_inline_mention = False

    def record_target(raw_target: object) -> None:
        nonlocal has_non_bot_mention, target_user_id

        candidate = str(raw_target).strip() if raw_target is not None else ""
        if not candidate:
            has_non_bot_mention = True
            return
        if _is_ignored_mention_target(candidate, normalized_bot_id):
            if candidate.lower() == "all":
                has_non_bot_mention = True
            return
        has_non_bot_mention = True
        target_user_id = candidate

    get_messages = getattr(event, "get_messages", None)
    messages = get_messages() if callable(get_messages) else ()
    if isinstance(messages, Iterable):
        for component in messages:
            if isinstance(component, AtAll):
                record_target("all")
                continue
            if isinstance(component, At):
                record_target(getattr(component, "qq", None))
                continue
            if not isinstance(component, Plain):
                continue
            text = getattr(component, "text", "") or ""
            inline_targets = _inline_mention_targets(text)
            display_targets = _onebot_display_mention_targets(text)
            has_unresolved_display_mention = _has_unresolved_onebot_display_mention(
                text
            )
            if inline_targets or display_targets or has_unresolved_display_mention:
                has_inline_mention = True
            for candidate in (*inline_targets, *display_targets):
                record_target(candidate)
            if has_unresolved_display_mention:
                record_target(None)

    if not has_inline_mention:
        get_message_str = getattr(event, "get_message_str", None)
        if callable(get_message_str):
            text = get_message_str()
            inline_targets = _inline_mention_targets(text)
            display_targets = _onebot_display_mention_targets(text)
            has_unresolved_display_mention = _has_unresolved_onebot_display_mention(
                text
            )
            for candidate in (*inline_targets, *display_targets):
                record_target(candidate)
            if has_unresolved_display_mention:
                record_target(None)

    for raw_target in _raw_onebot_mention_targets(event):
        record_target(raw_target)

    return MentionTargetResult(
        target_user_id=target_user_id,
        has_unresolved_mention=has_non_bot_mention and target_user_id is None,
    )


def target_user_from_event(
    event: Any,
    *,
    bot_id: str | None = None,
) -> str | None:
    """从 AstrBot 公开消息链提取最后一个有效 @ 用户。"""

    return mention_target_from_event(event, bot_id=bot_id).target_user_id


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
