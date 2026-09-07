"""游戏/社区签到领域的 typed 合约。

本模块只描述签到日历、社区任务和签到状态所需的数据，不接触 AstrBot event、
旧 ``Sender`` 或数据库 ORM。camelCase 映射、异常归类和 legacy 值对象组装都
在 infrastructure 边界完成，service 只消费这些校验过的值对象并保持错误可见。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from ...entry.event import EventActor
from ..player.contracts import RoleHeader


class CheckinFailureKind(StrEnum):
    """签到 transport 的可观察失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    SERVER = "server"
    CREDENTIAL = "credential"
    NOT_FOUND = "not_found"


class CheckinTransportError(Exception):
    """不会把服务端原文、URL 或凭据带到用户响应的签到错误。"""

    def __init__(
        self,
        kind: CheckinFailureKind | str,
        *,
        resource: str = "签到数据",
        detail: str = "",
    ) -> None:
        self.kind = CheckinFailureKind(kind)
        self.resource = resource
        self.detail = detail
        super().__init__(f"checkin transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """异常 repr 只保留类别和安全资源名，避免 detail 泄露。"""

        return f"CheckinTransportError(kind={self.kind.value!r}, resource={self.resource!r})"


@dataclass(frozen=True, slots=True)
class DayAward:
    """签到日历中一天的奖励。"""

    award_id: int
    period_id: int
    day_in_period: int
    award_name: str
    award_num: int
    icon_url: str = ""


@dataclass(frozen=True, slots=True)
class SignPeriod:
    """当前签到周期；时间戳保持服务端语义，由渲染层格式化。"""

    period_id: int
    name: str
    over_days: int
    start_date: int
    end_date: int


@dataclass(frozen=True, slots=True)
class SignRoleInfo:
    """签到接口返回的绑定角色信息。"""

    role_id: str
    role_name: str
    level: int
    head_url: str = ""


@dataclass(frozen=True, slots=True)
class SignCalendar:
    """签到日历快照。

    当日尚未签到 / 未绑定角色时，后端可能省略顶层签到状态字段；这些字段允许为
    None，由 use case 判空决定继续签到还是渲染。
    """

    today_signed: bool | None = None
    user_gold: int | None = None
    signin_time: int | None = None
    day_awards: tuple[DayAward, ...] = ()
    period: SignPeriod | None = None
    role_info: SignRoleInfo | None = None


@dataclass(frozen=True, slots=True)
class CommunityTask:
    """社区任务进度中的一项。"""

    mark_name: str | None
    remark: str
    complete_times: int
    times: int
    process: float = 0.0
    gain_exp: int = 0
    gain_gold: int = 0


@dataclass(frozen=True, slots=True)
class TaskProcess:
    """社区任务进度快照。"""

    daily_tasks: tuple[CommunityTask, ...] = ()


@dataclass(frozen=True, slots=True)
class CommunityPost:
    """供社区任务消费的帖子；payload 只在 transport 边界解析。"""

    post_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class SignStatus(StrEnum):
    """签到结果的稳定状态类别。"""

    DONE = "done"
    SKIP = "skip"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(slots=True)
class CheckinSnapshot:
    """一个账号当天的签到计数（新 schema 的记录投影，作为运行期累加器）。"""

    uid: str
    record_date: date
    game_sign: int = 0
    bbs_sign: int = 0
    bbs_detail: int = 0
    bbs_like: int = 0
    bbs_share: int = 0
    bbs_reply: int = 0


@dataclass(frozen=True, slots=True)
class CheckinOutcome:
    """一次账号签到的可观察结果。"""

    game_status: SignStatus
    bbs_status: SignStatus
    # 兼容手动签到展示的完整文本投影，不作为群报告的业务数据源。
    detail_lines: tuple[str, ...] = ()
    error: str = ""
    # 群报告直接消费两类结构化详情，避免从 detail_lines 反向推断业务归属。
    game_detail_lines: tuple[str, ...] = ()
    community_detail_lines: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        """批量计数语义：游戏或社区任务至少有一项完成即算成功。"""

        return self.game_status in (SignStatus.DONE, SignStatus.SKIP) or (
            self.bbs_status in (SignStatus.DONE, SignStatus.SKIP)
        )


@dataclass(frozen=True, slots=True)
class CheckinSummary:
    """批量签到的聚合结果。"""

    success: int = 0
    failed: int = 0
    game_success: int = 0
    bbs_success: int = 0


@dataclass(frozen=True, slots=True)
class GroupSignReport:
    """一个群的一类签到报告。"""

    report_type: str
    success: int
    failed: int
    summary_text: str
    detail_text: str = ""
    image_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class AutoSignReport:
    """一次自动签到的全局汇总与按群分组报告。"""

    summary_text: str
    group_reports: dict[str, tuple[GroupSignReport, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckinCalendarData:
    """签到日历渲染所需的聚合输入。"""

    calendar: SignCalendar
    tasks: TaskProcess | None = None
    total_sign_in_days: int = 0
    role_overview: RoleHeader | None = None
    snapshot: CheckinSnapshot | None = None


@dataclass(frozen=True, slots=True)
class CheckinCommandRequest:
    """签到命令的框架无关输入。"""

    actor: EventActor
    target_user_id: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    text: str = ""


class CheckinTransport(Protocol):
    """签到 use case 所需的最小 transport。"""

    async def get_sign_calendar(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignCalendar:
        """读取签到日历。"""
        ...

    async def game_sign(
        self,
        actor: EventActor,
        uid: str,
        award: DayAward,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        """执行一次游戏签到；已签到返回 SKIP。"""
        ...

    async def get_task_process(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> TaskProcess:
        """读取社区任务进度。"""
        ...

    async def bbs_sign(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        """执行社区签到。"""
        ...

    async def have_sign_in(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> int:
        """读取社区累计签到天数。"""
        ...

    async def get_role_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleHeader:
        """读取签到日历头部所需的轻量角色信息。"""
        ...

    async def get_post_list(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> tuple[CommunityPost, ...]:
        """读取社区任务所需的帖子列表。"""
        ...

    async def get_post_detail(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        """浏览一个帖子。"""
        ...

    async def do_like(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        """点赞一个帖子。"""
        ...

    async def do_share(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> bool:
        """分享帖子任务。"""
        ...

    async def do_reply(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        """回复一个帖子。"""
        ...


__all__ = [
    "AutoSignReport",
    "CheckinCalendarData",
    "CheckinCommandRequest",
    "CheckinFailureKind",
    "CheckinOutcome",
    "CheckinSnapshot",
    "CheckinSummary",
    "CheckinTransport",
    "CheckinTransportError",
    "CommunityPost",
    "CommunityTask",
    "DayAward",
    "GroupSignReport",
    "SignCalendar",
    "SignPeriod",
    "SignRoleInfo",
    "SignStatus",
    "TaskProcess",
]
