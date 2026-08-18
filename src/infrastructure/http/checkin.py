"""签到的 legacy 纯 API 适配器。

只在 transport 边界读取 rewrite 凭据并组装 legacy ``DNAUser`` 值对象；业务层
收到的始终是 typed checkin contracts。没有账号凭据或外部 API 结构异常时，返回
安全的 ``CheckinTransportError``，不把原始响应或 secret 带进日志/响应。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

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
from ...modules.player.contracts import RoleOverview


def _error_kind(response: Any) -> CheckinFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return CheckinFailureKind.NETWORK
    if isinstance(code, int) and code >= 400:
        return CheckinFailureKind.STATUS
    return CheckinFailureKind.SERVER


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


class DnaApiCheckinTransport:
    """用已保存凭据调用 legacy 纯 API 方法的签到 transport。"""

    def __init__(self, database: AsyncDatabase) -> None:
        self.database = database

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
                bot_id=actor.bot_id,
                uid=uid,
            )
        if record is None:
            raise CheckinTransportError(
                CheckinFailureKind.CREDENTIAL,
                resource="账号凭据",
                detail="credential record is missing",
            )
        try:
            from src.utils.database.models import DNAUser

            return DNAUser(
                user_id=credential_user_id,
                bot_id=actor.bot_id,
                uid=uid,
                cookie=record.app_cookie,
                dev_code=record.app_device_code,
                d_num=record.app_d_num,
                refresh_token=record.app_refresh_token,
                status=record.app_status,
                web_token=record.web_token,
                web_dev_code=record.web_device_code,
                web_d_num=record.web_d_num,
                web_refresh_token=record.web_refresh_token,
                web_status=record.web_status,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise CheckinTransportError(
                CheckinFailureKind.SERVER,
                resource="账号凭据",
                detail=f"legacy credential value construction failed: {type(error).__name__}",
            ) from None

    @staticmethod
    def _sign_calendar(data: Any) -> SignCalendar:
        from src.utils.api.model import DNACalendarSignRes

        payload = DNACalendarSignRes.model_validate(data)
        period = payload.period
        role_info = payload.roleInfo
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
            period=(
                None
                if period is None
                else SignPeriod(
                    period_id=period.id,
                    name=period.name,
                    over_days=period.overDays,
                    start_date=period.startDate,
                    end_date=period.endDate,
                )
            ),
            role_info=(
                None
                if role_info is None
                else SignRoleInfo(
                    role_id=role_info.roleId,
                    role_name=role_info.roleName,
                    level=role_info.level,
                    head_url=role_info.headUrl,
                )
            ),
        )

    @staticmethod
    def _task_process(data: Any) -> TaskProcess:
        from src.utils.api.model import DNATaskProcessRes

        payload = DNATaskProcessRes.model_validate(data)
        return TaskProcess(
            daily_tasks=tuple(
                CommunityTask(
                    mark_name=item.markName,
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

    async def get_sign_calendar(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignCalendar:
        try:
            from src.utils import dna_api

            response = await dna_api.sign_calendar(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._sign_calendar(_response_data(response, resource="签到日历"))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="签到日历") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="签到日历") from None

    @staticmethod
    def _game_sign_status(response: Any) -> SignStatus:
        if getattr(response, "is_success", False):
            return SignStatus.DONE
        if getattr(response, "code", None) == 711:
            return SignStatus.SKIP
        return SignStatus.FAILED

    @staticmethod
    def _bbs_sign_status(response: Any) -> SignStatus:
        if getattr(response, "is_success", False) or getattr(response, "code", None) == 10000:
            return SignStatus.DONE
        return SignStatus.FAILED

    async def game_sign(
        self,
        actor: EventActor,
        uid: str,
        award: DayAward,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        try:
            from src.utils import dna_api

            response = await dna_api.game_sign(
                await self._legacy_user(actor, uid, credential_user_id),
                award.award_id,
                award.period_id,
            )
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="游戏签到") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="游戏签到") from None
        return self._game_sign_status(response)

    async def get_task_process(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> TaskProcess:
        try:
            from src.utils import dna_api

            response = await dna_api.get_task_process(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._task_process(_response_data(response, resource="社区任务"))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区任务") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区任务") from None

    async def bbs_sign(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> SignStatus:
        try:
            from src.utils import dna_api

            response = await dna_api.bbs_sign(
                await self._legacy_user(actor, uid, credential_user_id),
            )
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区签到") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区签到") from None
        return self._bbs_sign_status(response)

    async def have_sign_in(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> int:
        try:
            from src.utils import dna_api

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
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区签到天数") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区签到天数") from None

    async def get_role_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        try:
            from src.utils import dna_api
            from src.infrastructure.http.player import DnaApiPlayerTransport

            response = await dna_api.get_default_role_for_tool(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return DnaApiPlayerTransport._overview(
                _response_data(response, resource="角色列表信息"),
            )
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="角色列表信息") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="角色列表信息") from None

    async def get_post_list(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> tuple[CommunityPost, ...]:
        try:
            from src.utils import dna_api

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
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区帖子") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区帖子") from None

    async def get_post_detail(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from src.utils import dna_api

            response = await dna_api.get_post_detail(
                post.post_id,
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区帖子") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区帖子") from None

    async def do_like(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from src.utils import dna_api

            response = await dna_api.do_like(
                await self._legacy_user(actor, uid, credential_user_id),
                post.payload,
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区点赞") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区点赞") from None

    async def do_share(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from src.utils import dna_api

            response = await dna_api.do_share(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区分享") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区分享") from None

    async def do_reply(
        self,
        actor: EventActor,
        uid: str,
        post: CommunityPost,
        *,
        credential_user_id: str,
    ) -> bool:
        try:
            from src.modules.checkin.reply_temps import get_random_reply
            from src.utils import dna_api

            response = await dna_api.do_reply(
                await self._legacy_user(actor, uid, credential_user_id),
                post.payload,
                get_random_reply(),
            )
            return bool(getattr(response, "is_success", False))
        except CheckinTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise CheckinTransportError(CheckinFailureKind.NETWORK, resource="社区回复") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise CheckinTransportError(CheckinFailureKind.SERVER, resource="社区回复") from None


__all__ = ["DnaApiCheckinTransport"]
