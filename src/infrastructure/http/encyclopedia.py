"""资料查询的 legacy API transport。

此层是 rewrite 与旧 DNAUID 纯 API 的唯一连接点：读取新数据库凭据、构造 legacy
``DNAUser``、校验响应并映射为 typed snapshot。异常只保留稳定类别，绝不把响应原文
或凭据带入用户消息。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from ...entry.event import EventActor
from ...infrastructure.persistence import AsyncDatabase, CredentialRepository
from ...infrastructure.resources.acceleration import accelerate_github_url
from ...modules.encyclopedia.contracts import (
    CalendarEvent,
    CalendarSnapshot,
    CodeEntry,
    CodeSnapshot,
    DraftSnapshot,
    EncyclopediaFailureKind,
    EncyclopediaTransportError,
    PlayerShortNote,
    WeeklyReport,
    WeeklyReportCategory,
    WeeklyReportItem,
)
from ...modules.player.contracts import (
    RoleAchievement,
    RoleHeader,
)
from .auth import is_credential_failure
from .concurrency import RequestConcurrencyGate, gated_transport_method

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CODE_URL = (
    "https://raw.githubusercontent.com/FlanChanXwO/"
    "astrbot_plugin_dna_resources/main/data/redeem_codes.json"
)
CodeProvider = Callable[[EventActor], Awaitable[Any] | Any]
_CODE_FIELDS = frozenset(
    {"code", "reward", "valid_from", "expires_at", "platforms", "servers"}
)
_CODE_PLATFORMS = frozenset({"pc", "android", "ios"})
_CODE_SERVERS = frozenset({"cn", "global"})
_CALENDAR_ROTATIONS = (
    ("魔灵", "moling", datetime(2026, 1, 3, 5, 0, tzinfo=SHANGHAI_TZ), 86400 * 3),
    ("周本", "zhouben", datetime(2025, 12, 29, 5, 0, tzinfo=SHANGHAI_TZ), 86400 * 7),
)


class _EncyclopediaProjection(BaseModel):
    """资料查询 transport 的消费者专用响应投影。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _RoleHeaderShowProjection(_EncyclopediaProjection):
    roleId: str
    roleName: str = ""
    level: int | None = None
    params: list[RoleAchievement] = Field(default_factory=list)


class _RoleHeaderInfoProjection(_EncyclopediaProjection):
    roleShow: _RoleHeaderShowProjection


class _RoleHeaderResponse(_EncyclopediaProjection):
    roleInfo: _RoleHeaderInfoProjection


class _DraftDoingProjection(_EncyclopediaProjection):
    draftCompleteNum: int = 0
    draftDoingNum: int = 0
    endTime: str | int | float | None = None
    productName: str | None = None
    startTime: str | int | float | None = None


class _DraftInfoProjection(_EncyclopediaProjection):
    draftDoingInfo: list[_DraftDoingProjection] | None = None
    draftDoingNum: int = 0
    draftMaxNum: int = 0


class _ShortNoteProjection(_EncyclopediaProjection):
    rougeLikeRewardCount: int
    rougeLikeRewardTotal: int
    currentTaskProgress: int
    maxDailyTaskProgress: int
    hardBossRewardCount: int
    hardBossRewardTotal: int
    dungeonReward: int
    dungeonRewardTotal: int
    draftInfo: _DraftInfoProjection | None = None


class _WeeklyItemProjection(_EncyclopediaProjection):
    itemId: int
    itemName: str
    quality: int = 0
    totalNum: str | int = "0"
    icon: str = ""


class _WeeklyCategoryProjection(_EncyclopediaProjection):
    categoryName: str
    items: list[_WeeklyItemProjection] = Field(default_factory=list)
    isBase: bool = False
    type: int = 0


class _WeeklyProjection(_EncyclopediaProjection):
    categories: list[_WeeklyCategoryProjection]
    startDate: str
    endDate: str
    weekType: int


class _CodeContractError(ValueError):
    """兑换码 provider 返回值不符合资源仓库 v1 契约。"""


def _code_contract_error(message: str) -> _CodeContractError:
    """统一构造内部契约异常；上层只暴露稳定 failure kind。"""

    return _CodeContractError(message)


def _parse_code_datetime(value: object, *, field_name: str) -> datetime:
    """解析必须带时区的资源仓库 ISO 8601 时间并统一到上海时区。"""

    if not isinstance(value, str) or not value:
        raise _code_contract_error(f"{field_name} must be an aware ISO datetime")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise _code_contract_error(f"{field_name} is not a valid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _code_contract_error(f"{field_name} must include a timezone")
    return parsed.astimezone(SHANGHAI_TZ)


def _parse_code_enum_list(
    value: object,
    *,
    field_name: str,
    allowed: frozenset[str],
) -> tuple[str, ...]:
    """校验可选枚举列表并保留资源文件中的顺序。"""

    if not isinstance(value, list) or not value:
        raise _code_contract_error(f"{field_name} must be a non-empty list")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise _code_contract_error(f"{field_name} contains an unsupported value")
    if len(set(value)) != len(value):
        raise _code_contract_error(f"{field_name} contains duplicates")
    return tuple(value)


def _error_kind(response: Any) -> EncyclopediaFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return EncyclopediaFailureKind.NETWORK
    if is_credential_failure(response):
        return EncyclopediaFailureKind.CREDENTIAL
    if isinstance(code, int) and code >= 400:
        return EncyclopediaFailureKind.STATUS
    return EncyclopediaFailureKind.SERVER


def _response_data(response: Any, *, resource: str) -> Any:
    """检查 legacy response 成功标志并隐藏 msg/data 原文。"""

    if not getattr(response, "is_success", False):
        raise EncyclopediaTransportError(
            _error_kind(response),
            resource=resource,
            detail=f"api response code={getattr(response, 'code', None)!r}",
        )
    data = getattr(response, "data", None)
    if data is None:
        raise EncyclopediaTransportError(
            EncyclopediaFailureKind.SERVER,
            resource=resource,
            detail="successful response has no data",
        )
    return data


def _parse_datetime(value: object, *, milliseconds: bool = False) -> datetime | None:
    """把 legacy 日期、秒时间戳或毫秒时间戳映射为上海时区 datetime。"""

    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = (
            float(value) / 1000
            if milliseconds or abs(value) > 10_000_000_000
            else float(value)
        )
        return datetime.fromtimestamp(timestamp, tz=SHANGHAI_TZ)
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        timestamp = (
            numeric / 1000 if milliseconds or abs(numeric) > 10_000_000_000 else numeric
        )
        return datetime.fromtimestamp(timestamp, tz=SHANGHAI_TZ)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern).replace(tzinfo=SHANGHAI_TZ)
                break
            except ValueError:
                continue
        else:
            raise
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _rotation_period(
    now: datetime,
    *,
    start_at: datetime,
    duration_seconds: int,
) -> tuple[datetime, datetime]:
    """复用 legacy 轮换起点和周期公式，但不导入带渲染副作用的旧模块。"""

    localized_now = (
        now.replace(tzinfo=SHANGHAI_TZ)
        if now.tzinfo is None
        else now.astimezone(SHANGHAI_TZ)
    )
    duration = timedelta(seconds=duration_seconds)
    period_index = int((localized_now - start_at).total_seconds() // duration_seconds)
    period_start = start_at + period_index * duration
    return period_start, period_start + duration


def _role_header(data: Any) -> RoleHeader:
    """将角色查询响应映射为便签、周报所需的最小角色头部。"""

    payload = _RoleHeaderResponse.model_validate(data)
    role_show = payload.roleInfo.roleShow
    return RoleHeader.model_validate(
        {
            "roleId": role_show.roleId,
            "roleName": role_show.roleName or "",
            "level": role_show.level,
            "params": [item.model_dump(by_alias=True) for item in role_show.params],
        },
    )


# 保留私有旧名称，避免外部脚本导入时突然失效；返回值已收窄为 RoleHeader。
def _role_overview(data: Any) -> RoleHeader:
    return _role_header(data)


class DnaApiEncyclopediaTransport:
    """用 rewrite 数据库凭据调用 legacy 资料 API 的读取 transport。"""

    def __init__(
        self,
        database: AsyncDatabase,
        *,
        code_provider: CodeProvider | None = None,
        code_url: str = DEFAULT_CODE_URL,
        acceleration_prefix: str | None = None,
        request_gate: RequestConcurrencyGate | None = None,
    ) -> None:
        self.database = database
        self._code_provider = code_provider
        self.acceleration_prefix = acceleration_prefix
        self.request_gate = request_gate
        self.code_url = accelerate_github_url(code_url, acceleration_prefix)

    async def _legacy_user(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
    ) -> Any:
        """按目标用户读取凭据，防止 @ 查询错用调用者凭据。"""

        async with self.database.session() as session:
            record = await CredentialRepository.get(
                session,
                user_id=credential_user_id,
                uid=uid,
            )
        if (
            record is None
            or record.app_status == "无效"
            or not record.has_app_credentials
        ):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.CREDENTIAL,
                resource="账号凭据",
                detail="credential record is missing or invalid",
            )
        try:
            from ...utils.database.models import DNAUser

            return DNAUser(
                user_id=credential_user_id,
                bot_id=actor.bot_id,
                uid=uid,
                cookie=record.app_cookie,
                dev_code=record.app_device_code,
                d_num=record.app_d_num,
                refresh_token=record.app_refresh_token,
                status=record.app_status,
            )
        except (AttributeError, TypeError, ValueError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.SERVER,
                resource="账号凭据",
                detail="legacy credential value construction failed",
            ) from None

    @staticmethod
    def _short_note(data: Any) -> PlayerShortNote:
        """映射便签实际消费的进度和锻造槽位字段。"""

        payload = _ShortNoteProjection.model_validate(data)
        draft_info = payload.draftInfo or _DraftInfoProjection()
        drafts = tuple(
            DraftSnapshot(
                product_name=draft.productName or "",
                start_at=_parse_datetime(draft.startTime),
                end_at=_parse_datetime(draft.endTime),
                completed=draft.draftCompleteNum > 0,
                draft_doing_num=draft.draftDoingNum,
                draft_complete_num=draft.draftCompleteNum,
            )
            for draft in draft_info.draftDoingInfo or ()
            if draft.productName or draft.endTime or draft.startTime
        )
        return PlayerShortNote(
            rouge_like_reward_count=payload.rougeLikeRewardCount,
            rouge_like_reward_total=payload.rougeLikeRewardTotal,
            current_task_progress=payload.currentTaskProgress,
            max_daily_task_progress=payload.maxDailyTaskProgress,
            hard_boss_reward_count=payload.hardBossRewardCount,
            hard_boss_reward_total=payload.hardBossRewardTotal,
            dungeon_reward=payload.dungeonReward,
            dungeon_reward_total=payload.dungeonRewardTotal,
            drafts=drafts,
            draft_doing_num=draft_info.draftDoingNum,
            draft_max_num=draft_info.draftMaxNum,
        )

    @staticmethod
    def _weekly(report_data: Any, role_data: Any) -> WeeklyReport:
        """按周报 renderer 实际读取的字段解析分类、资源项和角色头部。"""

        payload = _WeeklyProjection.model_validate(report_data)
        categories = tuple(
            WeeklyReportCategory(
                category_name=category.categoryName,
                is_base=bool(category.isBase),
                category_type=category.type,
                items=tuple(
                    WeeklyReportItem(
                        item_id=item.itemId,
                        item_name=item.itemName,
                        quality=item.quality,
                        total_num=str(item.totalNum),
                        icon=item.icon,
                    )
                    for item in category.items
                ),
            )
            for category in payload.categories
        )
        return WeeklyReport(
            week_type=payload.weekType,
            start_date=payload.startDate,
            end_date=payload.endDate,
            categories=categories,
            role_overview=_role_header(role_data),
        )

    @staticmethod
    def _calendar_event(
        item: Mapping[str, Any],
        *,
        title_key: str = "name",
        pic_key: str = "pic",
        milliseconds: bool = True,
    ) -> CalendarEvent:
        return CalendarEvent(
            title=str(item.get(title_key) or ""),
            pic=str(item.get(pic_key) or ""),
            start_at=_parse_datetime(
                item.get("startTime", item.get("createTime")), milliseconds=milliseconds
            ),
            end_at=_parse_datetime(item.get("endTime"), milliseconds=milliseconds),
        )

    @staticmethod
    def _base_calendar_events(now: datetime) -> tuple[CalendarEvent, ...]:
        """按 legacy 的魔灵/周本轮换基准时间生成纯资料事件。"""

        return tuple(
            CalendarEvent(
                title=title,
                pic=f"{name}.png",
                start_at=period[0],
                end_at=period[1],
            )
            for title, name, start_at, duration_seconds in _CALENDAR_ROTATIONS
            for period in (
                _rotation_period(
                    now,
                    start_at=start_at,
                    duration_seconds=duration_seconds,
                ),
            )
        )

    @classmethod
    def _calendar_from_payloads(
        cls,
        activity_data: Any,
        wiki_data: Any,
    ) -> CalendarSnapshot:
        """合并新旧日历接口，并保留 legacy 的轮换过滤规则。"""

        events: list[CalendarEvent] = []
        if isinstance(wiki_data, list):
            for section in wiki_data:
                if not isinstance(section, Mapping) or section.get("sectionType") != 3:
                    continue
                for activity_up in section.get("activityUps") or []:
                    if not isinstance(activity_up, Mapping):
                        continue
                    parent_name = str(activity_up.get("name") or "")
                    for content in activity_up.get("contents") or []:
                        if not isinstance(content, Mapping):
                            continue
                        event = cls._calendar_event(
                            {
                                **content,
                                "name": parent_name or content.get("name", ""),
                                "createTime": activity_up.get("createTime"),
                                "endTime": activity_up.get("endTime"),
                            },
                        )
                        if event.title:
                            events.append(event)
                for activity in section.get("activities") or []:
                    if not isinstance(activity, Mapping):
                        continue
                    event = cls._calendar_event(activity)
                    if event.title:
                        events.append(event)

        if isinstance(activity_data, Mapping):
            for activity in activity_data.get("activities") or []:
                if not isinstance(activity, Mapping):
                    continue
                if activity.get("cycleDay", -1) != -1:
                    continue
                if "委托密函轮换" in str(activity.get("name") or ""):
                    continue
                event = cls._calendar_event(
                    activity,
                    pic_key="icon",
                )
                if event.title:
                    events.append(event)

        if not events:
            return CalendarSnapshot()
        return CalendarSnapshot(
            events=cls._base_calendar_events(datetime.now(tz=SHANGHAI_TZ))
            + tuple(events),
        )

    @gated_transport_method
    async def get_short_note(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> PlayerShortNote:
        try:
            from ...utils import dna_api

            legacy_user = await self._legacy_user(actor, uid, credential_user_id)
            short_note = _response_data(
                await dna_api.get_short_note_info(legacy_user),
                resource="日常便签数据",
            )
            role_data = _response_data(
                await dna_api.get_default_role_for_tool(legacy_user),
                resource="角色列表信息",
            )
            snapshot = self._short_note(short_note)
            return replace(snapshot, role_overview=_role_header(role_data))
        except EncyclopediaTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.NETWORK,
                resource="日常便签数据",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.SERVER,
                resource="日常便签数据",
            ) from None

    @gated_transport_method
    async def get_weekly_report(
        self,
        actor: EventActor,
        uid: str,
        week_type: int,
        *,
        credential_user_id: str,
    ) -> WeeklyReport:
        try:
            from ...utils import dna_api

            legacy_user = await self._legacy_user(actor, uid, credential_user_id)
            report_data = _response_data(
                await dna_api.get_item_weekly_report(legacy_user, week_type),
                resource="周报数据",
            )
            role_data = _response_data(
                await dna_api.get_default_role_for_tool(legacy_user),
                resource="角色列表信息",
            )
            return self._weekly(report_data, role_data)
        except EncyclopediaTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.NETWORK,
                resource="周报数据",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.SERVER,
                resource="周报数据",
            ) from None

    @gated_transport_method
    async def get_calendar(self, actor: EventActor) -> CalendarSnapshot:
        del actor
        activity_error: EncyclopediaTransportError | None = None
        wiki_error: EncyclopediaTransportError | None = None
        activity_data: Any = None
        wiki_data: Any = None
        try:
            from ...utils import dna_api

            try:
                activity_data = _response_data(
                    await dna_api.get_activity_info(),
                    resource="活动日历数据",
                )
            except EncyclopediaTransportError as error:
                activity_error = error
            try:
                wiki_data = await dna_api.get_calendar_info()
                if wiki_data is not None and not isinstance(wiki_data, list):
                    raise EncyclopediaTransportError(
                        EncyclopediaFailureKind.SERVER,
                        resource="旧版日历数据",
                        detail="calendar payload is not a list",
                    )
            except EncyclopediaTransportError as error:
                wiki_error = error

            snapshot = self._calendar_from_payloads(activity_data, wiki_data)
            if not snapshot.events:
                raise (
                    activity_error
                    or wiki_error
                    or EncyclopediaTransportError(
                        EncyclopediaFailureKind.NOT_FOUND,
                        resource="日历数据",
                    )
                )
            return snapshot
        except EncyclopediaTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.NETWORK,
                resource="日历数据",
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.SERVER,
                resource="日历数据",
            ) from None

    async def _default_code_provider(self, _actor: EventActor) -> Any:
        """读取资源仓库中的只读兑换码 JSON。"""

        async with (
            aiohttp.ClientSession() as session,
            session.get(self.code_url) as response,
        ):
            if response.status >= 400:
                raise EncyclopediaTransportError(
                    EncyclopediaFailureKind.STATUS,
                    resource="兑换码",
                    detail=f"provider status={response.status}",
                )
            return json.loads(await response.text())

    async def _provided_codes(self, actor: EventActor) -> Any:
        provider = self._code_provider or self._default_code_provider
        result = provider(actor)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _codes(data: Any, *, now: datetime | None = None) -> CodeSnapshot:
        """解析资源仓库兑换码契约并过滤计划中/已过期条目。"""

        if not isinstance(data, Mapping):
            raise _code_contract_error("payload must be an object")
        if set(data) - {"format_version", "data"}:
            raise _code_contract_error("payload contains unknown fields")
        if (
            type(data.get("format_version")) is not int
            or data.get("format_version") != 1
        ):
            raise _code_contract_error("unsupported format_version")
        if not isinstance(data.get("data"), list):
            raise _code_contract_error("data must be a list")

        current = (
            datetime.now(tz=SHANGHAI_TZ)
            if now is None
            else now.replace(tzinfo=SHANGHAI_TZ)
            if now.tzinfo is None
            else now.astimezone(SHANGHAI_TZ)
        )
        entries: list[CodeEntry] = []
        seen_codes: set[str] = set()
        for item in data["data"]:
            if not isinstance(item, Mapping):
                raise _code_contract_error("code entry must be an object")
            if set(item) - _CODE_FIELDS:
                raise _code_contract_error("code entry contains unknown fields")

            raw_code = item.get("code")
            if not isinstance(raw_code, str) or not raw_code.strip():
                raise _code_contract_error("code must be non-empty text")
            code = raw_code.strip()
            if code in seen_codes:
                raise _code_contract_error("code values must be unique")
            seen_codes.add(code)

            reward = item.get("reward")
            if "reward" in item and not isinstance(reward, str):
                raise _code_contract_error("reward must be text")

            valid_from = (
                _parse_code_datetime(item["valid_from"], field_name="valid_from")
                if "valid_from" in item
                else None
            )
            expires_at = (
                _parse_code_datetime(item["expires_at"], field_name="expires_at")
                if "expires_at" in item
                else None
            )
            if (
                valid_from is not None
                and expires_at is not None
                and valid_from >= expires_at
            ):
                raise _code_contract_error("valid_from must be before expires_at")

            platforms = (
                _parse_code_enum_list(
                    item["platforms"],
                    field_name="platforms",
                    allowed=_CODE_PLATFORMS,
                )
                if "platforms" in item
                else ()
            )
            servers = (
                _parse_code_enum_list(
                    item["servers"],
                    field_name="servers",
                    allowed=_CODE_SERVERS,
                )
                if "servers" in item
                else ()
            )

            if (valid_from is None or valid_from <= current) and (
                expires_at is None or expires_at > current
            ):
                entries.append(
                    CodeEntry(
                        code=code,
                        expires_at=expires_at,
                        reward=reward,
                        valid_from=valid_from,
                        platforms=platforms,
                        servers=servers,
                    ),
                )
        return CodeSnapshot(
            codes=tuple(entry.code for entry in entries),
            expires_at=entries[0].expires_at if entries else None,
            entries=tuple(entries),
        )

    @gated_transport_method
    async def get_codes(self, actor: EventActor) -> CodeSnapshot:
        try:
            return self._codes(await self._provided_codes(actor))
        except EncyclopediaTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.NETWORK,
                resource="兑换码",
            ) from None
        except _CodeContractError:
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.CONTRACT,
                resource="兑换码",
            ) from None
        except (TypeError, ValueError, json.JSONDecodeError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.CONTRACT,
                resource="兑换码",
            ) from None
        except (AttributeError, KeyError):
            raise EncyclopediaTransportError(
                EncyclopediaFailureKind.SERVER,
                resource="兑换码",
            ) from None


__all__ = ["DEFAULT_CODE_URL", "DnaApiEncyclopediaTransport"]
