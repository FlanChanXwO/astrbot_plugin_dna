"""签到的 legacy 纯 API 适配器。

只在 transport 边界读取 rewrite 凭据并组装 legacy ``DNAUser`` 值对象；业务层
收到的始终是 typed checkin contracts。没有账号凭据或外部 API 结构异常时，返回
安全的 ``CheckinTransportError``，不把原始响应或 secret 带进日志/响应。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...entry.event import EventActor
from ...infrastructure.persistence import AsyncDatabase, CredentialRepository
from ...modules.checkin.contracts import (
    CheckinFailureKind,
    CheckinTransportError,
    CommunityPost,
    CommunityTask,
    DayAward,
    SignCalendar,
    SignPeriod,
    SignRoleInfo,
    SignStatus,
    TaskProcess,
)
from ...modules.player.contracts import RoleHeader
from ...utils.constants.sign_bbs_mark import BBSMarkName
from .app import AppTransportError, AppTransportFailureKind
from .auth import is_credential_failure
from .concurrency import RequestConcurrencyGate, gated_transport_method


def _error_kind(response: Any) -> CheckinFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return CheckinFailureKind.NETWORK
    if is_credential_failure(response):
        return CheckinFailureKind.CREDENTIAL
    if isinstance(code, int) and code >= 400:
        return CheckinFailureKind.STATUS
    return CheckinFailureKind.SERVER


def _app_error(
    error: AppTransportError,
    *,
    resource: str,
) -> CheckinTransportError:
    """Map the shared App transport failure into the check-in error contract.

    Args:
        error: Failure raised by the shared App REST transport.
        resource: Safe check-in resource name used for diagnostics.

    Returns:
        A redacted check-in transport error with the most specific failure kind.
    """

    if error.status_code in (401, 403):
        kind = CheckinFailureKind.CREDENTIAL
    elif error.kind is AppTransportFailureKind.NETWORK:
        kind = CheckinFailureKind.NETWORK
    elif error.kind is AppTransportFailureKind.STATUS:
        kind = CheckinFailureKind.STATUS
    else:
        kind = CheckinFailureKind.SERVER
    return CheckinTransportError(
        kind,
        resource=resource,
        detail=(
            f"app transport kind={error.kind.value} "
            f"status={error.status_code!r}"
        ),
    )


def _response_data(response: Any, *, resource: str) -> Any:
    """检查 legacy response 成功标志并隐藏 msg/data 原文。"""

    if not getattr(response, "is_success", False):
        raise CheckinTransportError(
            _error_kind(response),
            resource=resource,
            detail=f"api response code={getattr(response, 'code', None)!r}",
        )
    data = getattr(response, "data", None)
    if data is None:
        raise CheckinTransportError(
            CheckinFailureKind.SERVER,
            resource=resource,
            detail="successful response has no data",
        )
    return data


class _CheckinProjection(BaseModel):
    """签到查询 transport 的消费者专用投影。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _SignCalendarAwardProjection(_CheckinProjection):
    id: int
    periodId: int
    dayInPeriod: int
    awardName: str
    awardNum: int
    iconUrl: str = ""


class _SignCalendarPeriodProjection(_CheckinProjection):
    id: int
    name: str
    overDays: int
    startDate: int
    endDate: int


class _SignCalendarRoleInfoProjection(_CheckinProjection):
    roleId: str
    roleName: str
    level: int
    headUrl: str = ""


class _SignCalendarProjection(_CheckinProjection):
    todaySignin: bool | None = None
    userGoldNum: int | None = None
    dayAward: list[_SignCalendarAwardProjection] = Field(default_factory=list)
    signinTime: int | None = None
    period: _SignCalendarPeriodProjection
    roleInfo: object | None = None


class _CommunityTaskProjection(_CheckinProjection):
    remark: str
    completeTimes: int
    times: int
    process: float = 0.0
    gainExp: int = 0
    gainGold: int = 0


class _TaskProcessProjection(_CheckinProjection):
    dailyTask: list[_CommunityTaskProjection]


class DnaApiCheckinTransport:
    """用已保存凭据调用 legacy 纯 API 方法的签到 transport。"""

    def __init__(
        self,
        database: AsyncDatabase,
        request_gate: RequestConcurrencyGate | None = None,
    ) -> None:
        self.database = database
        self.request_gate = request_gate

    async def _legacy_user(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
    ) -> Any:
        async with self.database.session() as session:
            record = await CredentialRepository.get(
                session,
                user_id=credential_user_id,
                uid=uid,
            )
        if (
            record is None
            or record.app_status == "无效"
            or not record.app_cookie.strip()
            or not record.app_device_code.strip()
        ):
            raise CheckinTransportError(
                CheckinFailureKind.CREDENTIAL,
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
        except (AttributeError, TypeError, ValueError) as error:
            raise CheckinTransportError(
                CheckinFailureKind.SERVER,
                resource="账号凭据",
                detail=f"legacy credential value construction failed: {type(error).__name__}",
            ) from None

    @staticmethod
    def _sign_calendar(data: Any) -> SignCalendar:
        """只校验签到日历自身需要的字段。

        ``roleInfo`` 仅用于旧接口返回的附带信息，日历命令实际使用的是另一个
        角色头部查询；因此该可选嵌套块不完整时按 ``None`` 处理，而不影响周期
        和奖励日历的严格校验。
        """

        payload = _SignCalendarProjection.model_validate(data)
        role_info = None
        if payload.roleInfo is not None:
            try:
                role = _SignCalendarRoleInfoProjection.model_validate(payload.roleInfo)
            except ValidationError:
                role = None
            if role is not None:
                role_info = SignRoleInfo(
                    role_id=role.roleId,
                    role_name=role.roleName,
                    level=role.level,
                    head_url=role.headUrl,
                )
        period = payload.period
        return SignCalendar(
            today_signed=payload.todaySignin,
            user_gold=payload.userGoldNum,
            signin_time=payload.signinTime,
            day_awards=tuple(
                DayAward(
                    award_id=item.id,
                    period_id=item.periodId,
                    day_in_period=item.dayInPeriod,
                    award_name=item.awardName,
                    award_num=item.awardNum,
                    icon_url=item.iconUrl,
                )
                for item in payload.dayAward
            ),
            period=SignPeriod(
                period_id=period.id,
                name=period.name,
                over_days=period.overDays,
                start_date=period.startDate,
                end_date=period.endDate,
            ),
            role_info=role_info,
        )

    @staticmethod
    def _task_process(data: Any) -> TaskProcess:
        """解析任务实际消费的进度字段，忽略未使用的 ``skipType`` 等字段。"""

        payload = _TaskProcessProjection.model_validate(data)
        return TaskProcess(
            daily_tasks=tuple(
                CommunityTask(
                    mark_name=BBSMarkName.get_mark_name(item.remark),
                    remark=item.remark,
                    complete_times=item.completeTimes,
                    times=item.times,
                    process=item.process,
                    gain_exp=item.gainExp,
                    gain_gold=item.gainGold,
                )
                for item in payload.dailyTask
            ),
        )

    @gated_transport_method
    async def get_sign_calendar(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignCalendar:
        try:
            from ...utils import dna_api

            response = await dna_api.sign_calendar(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._sign_calendar(_response_data(response, resource="签到日历"))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="签到日历") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="签到日历"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="签到日历"
            ) from None

    @staticmethod
    def _game_sign_status(response: Any) -> SignStatus:
        if getattr(response, "is_success", False):
            return SignStatus.DONE
        if getattr(response, "code", None) == 711:
            return SignStatus.SKIP
        if is_credential_failure(response):
            raise CheckinTransportError(
                CheckinFailureKind.CREDENTIAL,
                resource="游戏签到",
                detail=f"api response code={getattr(response, 'code', None)!r}",
            )
        return SignStatus.FAILED

    @staticmethod
    def _bbs_sign_status(response: Any) -> SignStatus:
        if (
            getattr(response, "is_success", False)
            or getattr(response, "code", None) == 10000
        ):
            return SignStatus.DONE
        if is_credential_failure(response):
            raise CheckinTransportError(
                CheckinFailureKind.CREDENTIAL,
                resource="社区签到",
                detail=f"api response code={getattr(response, 'code', None)!r}",
            )
        return SignStatus.FAILED

    @gated_transport_method
    async def game_sign(
        self,
        actor: EventActor,
        uid: str,
        award: DayAward,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        try:
            from ...utils import dna_api

            response = await dna_api.game_sign(
                await self._legacy_user(actor, uid, credential_user_id),
                award.award_id,
                award.period_id,
            )
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="游戏签到") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="游戏签到"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="游戏签到"
            ) from None
        return self._game_sign_status(response)

    @gated_transport_method
    async def get_task_process(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> TaskProcess:
        try:
            from ...utils import dna_api

            response = await dna_api.get_task_process(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._task_process(_response_data(response, resource="社区任务"))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区任务") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区任务"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区任务"
            ) from None

    @gated_transport_method
    async def bbs_sign(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        try:
            from ...utils import dna_api

            response = await dna_api.bbs_sign(
                await self._legacy_user(actor, uid, credential_user_id),
            )
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区签到") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区签到"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区签到"
            ) from None
        return self._bbs_sign_status(response)

    @gated_transport_method
    async def have_sign_in(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> int:
        try:
            from ...utils import dna_api

            response = await dna_api.have_sign_in(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            data = _response_data(response, resource="社区签到天数")
            if not isinstance(data, dict):
                raise CheckinTransportError(
                    CheckinFailureKind.SERVER,
                    resource="社区签到天数",
                    detail="successful response has no dict data",
                )
            return int(data.get("totalSignInDay", 0) or 0)
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区签到天数") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区签到天数"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区签到天数"
            ) from None

    @gated_transport_method
    async def get_role_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleHeader:
        try:
            from ...utils import dna_api
            from .player import DnaApiPlayerTransport

            response = await dna_api.get_default_role_for_tool(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return DnaApiPlayerTransport._role_header(
                _response_data(response, resource="角色列表信息"),
            )
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="角色列表信息") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="角色列表信息"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="角色列表信息"
            ) from None

    @gated_transport_method
    async def get_post_list(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> tuple[CommunityPost, ...]:
        try:
            from ...utils import dna_api

            response = await dna_api.get_post_list(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            data = _response_data(response, resource="社区帖子")
            posts = data.get("postList", []) if isinstance(data, dict) else []
            return tuple(
                CommunityPost(
                    post_id=str(post.get("postId", "")),
                    payload=post,
                )
                for post in posts
                if isinstance(post, dict) and post.get("postId")
            )
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区帖子") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区帖子"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区帖子"
            ) from None

    @gated_transport_method
    async def get_post_detail(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from ...utils import dna_api

            response = await dna_api.get_post_detail(
                post.post_id,
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区帖子") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区帖子"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区帖子"
            ) from None

    @gated_transport_method
    async def do_like(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from ...utils import dna_api

            response = await dna_api.do_like(
                await self._legacy_user(actor, uid, credential_user_id),
                post.payload,
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区点赞") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区点赞"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区点赞"
            ) from None

    @gated_transport_method
    async def do_share(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from ...utils import dna_api

            response = await dna_api.do_share(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区分享") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区分享"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区分享"
            ) from None

    @gated_transport_method
    async def do_reply(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from ...modules.checkin.reply_temps import get_random_reply
            from ...utils import dna_api

            response = await dna_api.do_reply(
                await self._legacy_user(actor, uid, credential_user_id),
                post.payload,
                get_random_reply(),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except AppTransportError as error:
            raise _app_error(error, resource="社区回复") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(
                CheckinFailureKind.NETWORK, resource="社区回复"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(
                CheckinFailureKind.SERVER, resource="社区回复"
            ) from None


__all__ = ["DnaApiCheckinTransport"]
