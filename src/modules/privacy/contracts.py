"""隐私域的框架无关返回值。"""

from __future__ import annotations

from dataclasses import dataclass

from ...entry.event import EventActor

PrivacyActor = EventActor


@dataclass(frozen=True, slots=True)
class PrivacySnapshot:
    """个人设置的默认值快照。"""

    allow_peek: bool
    uid_hidden: bool


@dataclass(frozen=True, slots=True)
class QueryResolution:
    """记录 @ 查询最终使用的用户和是否因隐私被阻止。"""

    requested_user_id: str | None
    resolved_user_id: str
    blocked: bool


__all__ = ["PrivacyActor", "PrivacySnapshot", "QueryResolution"]
