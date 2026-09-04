"""便签、周报、日历和资料查询的 typed 合约。

本模块不依赖 AstrBot event、旧 Sender 或 Pillow。legacy API 的 camelCase 映射、
异常归类和运行期素材读取都在 infrastructure 边界完成，service 只消费这些值对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from ...entry.event import EventActor
from ..player.contracts import RoleOverview


class EncyclopediaFailureKind(StrEnum):
    """资料读取 transport 的可观察失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    CONTRACT = "contract"
    SERVER = "server"
    CREDENTIAL = "credential"
    NOT_FOUND = "not_found"
    RESOURCE = "resource"


class EncyclopediaTransportError(Exception):
    """不把服务端原文、URL 或凭据带到用户响应的资料读取错误。"""

    def __init__(
        self,
        kind: EncyclopediaFailureKind | str,
        *,
        resource: str = "资料数据",
        detail: str = "",
    ) -> None:
        self.kind = EncyclopediaFailureKind(kind)
        self.resource = resource
        self.detail = detail
        super().__init__(f"encyclopedia transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """异常 repr 只保留类别和安全资源名，避免 detail 泄露。"""

        return (
            "EncyclopediaTransportError("
            f"kind={self.kind.value!r}, resource={self.resource!r})"
        )


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    """一个锻造槽位的完整合法字段。"""

    product_name: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    completed: bool = False
    draft_doing_num: int = 0
    draft_complete_num: int = 0


@dataclass(frozen=True, slots=True)
class PlayerShortNote:
    """便签进度、锻造槽位和角色统计。"""

    rouge_like_reward_count: int = 0
    rouge_like_reward_total: int = 0
    current_task_progress: int = 0
    max_daily_task_progress: int = 0
    hard_boss_reward_count: int = 0
    hard_boss_reward_total: int = 0
    dungeon_reward: int = 0
    dungeon_reward_total: int = 0
    drafts: tuple[DraftSnapshot, ...] = ()
    draft_doing_num: int = 0
    draft_max_num: int = 0
    role_overview: RoleOverview | None = None


@dataclass(frozen=True, slots=True)
class WeeklyReportItem:
    """周报资源项；名称和数量不在 DTO 层截断。"""

    item_id: int
    item_name: str
    quality: int = 0
    total_num: str = "0"
    icon: str = ""


@dataclass(frozen=True, slots=True)
class WeeklyReportCategory:
    """周报分类及其全部资源项。"""

    category_name: str
    items: tuple[WeeklyReportItem, ...] = ()
    is_base: bool = False
    category_type: int = 0


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    """本周或上周资源获取统计。"""

    week_type: int
    start_date: str
    end_date: str
    categories: tuple[WeeklyReportCategory, ...] = ()
    role_overview: RoleOverview | None = None


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """活动日历中的一项；时间缺失时保留 None 而非伪造日期。"""

    title: str
    pic: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CalendarSnapshot:
    """活动日历快照。"""

    events: tuple[CalendarEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeEntry:
    """资源仓库中的一个兑换码及其可选展示/适用范围字段。"""

    code: str
    expires_at: datetime | None = None
    reward: str | None = None
    valid_from: datetime | None = None
    platforms: tuple[str, ...] = ()
    servers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeSnapshot:
    """当前兑换码列表。

    ``expires_at`` 保留兼容 fixture 和旧输出的共同截止时间；真实 provider 可用
    ``entries`` 保留每个兑换码各自的截止时间。
    """

    codes: tuple[str, ...] = ()
    expires_at: datetime | None = None
    entries: tuple[CodeEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class EncyclopediaRequest:
    """资料命令的框架无关输入。"""

    actor: EventActor
    target_user_id: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    text: str = ""


class EncyclopediaTransport(Protocol):
    """资料 use case 所需的最小读取 transport。"""

    async def get_short_note(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> PlayerShortNote:
        """读取便签和角色总览。"""
        ...

    async def get_weekly_report(
        self,
        actor: EventActor,
        uid: str,
        week_type: int,
        *,
        credential_user_id: str,
    ) -> WeeklyReport:
        """读取周报和角色总览。"""
        ...

    async def get_calendar(self, actor: EventActor) -> CalendarSnapshot:
        """读取活动日历。"""
        ...

    async def get_codes(self, actor: EventActor) -> CodeSnapshot:
        """读取兑换码 provider。"""
        ...


StaminaSnapshot = PlayerShortNote
WeeklyReportSnapshot = WeeklyReport


__all__ = [
    "CalendarEvent",
    "CalendarSnapshot",
    "CodeEntry",
    "CodeSnapshot",
    "DraftSnapshot",
    "EncyclopediaFailureKind",
    "EncyclopediaRequest",
    "EncyclopediaTransport",
    "EncyclopediaTransportError",
    "PlayerShortNote",
    "StaminaSnapshot",
    "WeeklyReport",
    "WeeklyReportCategory",
    "WeeklyReportItem",
    "WeeklyReportSnapshot",
]
