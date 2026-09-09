"""玩家查询的 legacy 纯 API 适配器。

只在 transport 边界读取 rewrite 凭据并组装 legacy ``DNAUser`` 值对象；业务层
收到的始终是 typed player contracts。没有账号凭据或外部 API 结构异常时，返回
安全的 ``PlayerTransportError``，不把原始响应或 secret 带进日志/响应。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from ...entry.event import EventActor
from ...infrastructure.persistence import AsyncDatabase, CredentialRepository
from ...modules.player import messages
from ...modules.player.contracts import (
    DamageCalculation,
    DamageSnapshot,
    PlayerFailureKind,
    PlayerTransportError,
    RoleAchievement,
    RoleDetail,
    RoleHeader,
    RoleItem,
    RoleOverview,
    WeaponDetail,
    WeaponItem,
)
from .auth import is_credential_failure
from .concurrency import RequestConcurrencyGate, gated_transport_method


def _error_kind(response: Any) -> PlayerFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return PlayerFailureKind.NETWORK
    if is_credential_failure(response):
        return PlayerFailureKind.CREDENTIAL
    if isinstance(code, int) and code >= 400:
        return PlayerFailureKind.STATUS
    return PlayerFailureKind.SERVER


def _response_data(response: Any, *, resource: str) -> Any:
    """检查 legacy response 成功标志并隐藏 msg/data 原文。"""

    if not getattr(response, "is_success", False):
        raise PlayerTransportError(
            _error_kind(response),
            resource=resource,
            detail=f"api response code={getattr(response, 'code', None)!r}",
        )
    data = getattr(response, "data", None)
    if data is None:
        raise PlayerTransportError(
            PlayerFailureKind.SERVER,
            resource=resource,
            detail="successful response has no data",
        )
    return data


class _PlayerProjection(BaseModel):
    """玩家查询 transport 的局部响应模型，不复用全量 legacy response。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _RoleAchievementTotalProjection(_PlayerProjection):
    total: int = 0


class _RoleCardShowProjection(_PlayerProjection):
    roleChars: list[RoleItem]
    langRangeWeapons: list[WeaponItem]
    closeWeapons: list[WeaponItem]
    level: int
    params: list[RoleAchievement]
    roleId: str
    roleName: str
    roleAchv: _RoleAchievementTotalProjection


class _RoleCardInfoProjection(_PlayerProjection):
    roleShow: _RoleCardShowProjection


class _RoleCardResponse(_PlayerProjection):
    roleInfo: _RoleCardInfoProjection


class _RoleHeaderShowProjection(_PlayerProjection):
    roleId: str
    roleName: str = ""
    level: int | None = None
    params: list[RoleAchievement] = Field(default_factory=list)


class _RoleHeaderInfoProjection(_PlayerProjection):
    roleShow: _RoleHeaderShowProjection


class _RoleHeaderResponse(_PlayerProjection):
    roleInfo: _RoleHeaderInfoProjection


class _RoleDetailResponse(_PlayerProjection):
    charDetail: dict[str, Any]


class _WeaponDetailResponse(_PlayerProjection):
    weaponDetail: dict[str, Any]


class DnaApiPlayerTransport:
    """用已保存凭据调用 legacy 纯 API 方法的读取 transport。"""

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
            or not record.has_app_credentials
        ):
            raise PlayerTransportError(
                PlayerFailureKind.CREDENTIAL,
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
            raise PlayerTransportError(
                PlayerFailureKind.SERVER,
                resource="账号凭据",
                detail=f"legacy credential value construction failed: {type(error).__name__}",
            ) from None

    @staticmethod
    def _overview(data: Any) -> RoleOverview:
        """解析角色卡片所需的完整展柜投影。"""

        payload = _RoleCardResponse.model_validate(data)
        role_show = payload.roleInfo.roleShow
        return RoleOverview.model_validate(
            {
                "roleId": role_show.roleId,
                "roleName": role_show.roleName or "",
                "level": role_show.level,
                "params": [item.model_dump(by_alias=True) for item in role_show.params],
                "achievementTotal": role_show.roleAchv.total,
                "roleChars": [
                    item.model_dump(by_alias=True) for item in role_show.roleChars
                ],
                "langRangeWeapons": [
                    item.model_dump(by_alias=True)
                    for item in role_show.langRangeWeapons
                ],
                "closeWeapons": [
                    item.model_dump(by_alias=True) for item in role_show.closeWeapons
                ],
            },
        )

    @staticmethod
    def _role_header(data: Any) -> RoleHeader:
        """解析只需要身份、等级和统计项的轻量角色投影。"""

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

    @staticmethod
    def _role_detail(data: Any) -> RoleDetail:
        payload = _RoleDetailResponse.model_validate(data)
        return RoleDetail.model_validate(payload.charDetail)

    @staticmethod
    def _weapon_detail(data: Any) -> WeaponDetail:
        payload = _WeaponDetailResponse.model_validate(data)
        return WeaponDetail.model_validate(payload.weaponDetail)

    @gated_transport_method
    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        try:
            from ...utils import dna_api

            response = await dna_api.get_default_role_for_tool(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._overview(_response_data(response, resource="角色列表信息"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK, resource="角色列表信息"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(
                PlayerFailureKind.SERVER, resource="角色列表信息"
            ) from None

    @gated_transport_method
    async def get_role_detail(
        self,
        actor: EventActor,
        uid: str,
        char_id: int,
        char_eid: str,
        *,
        credential_user_id: str,
    ) -> RoleDetail:
        try:
            from ...utils import dna_api

            response = await dna_api.get_role_detail(
                await self._legacy_user(actor, uid, credential_user_id),
                str(char_id),
                char_eid,
            )
            return self._role_detail(_response_data(response, resource="角色详情"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK, resource="角色详情"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(
                PlayerFailureKind.SERVER, resource="角色详情"
            ) from None

    @gated_transport_method
    async def get_weapon_detail(
        self,
        actor: EventActor,
        uid: str,
        weapon_id: int,
        weapon_eid: str,
        *,
        credential_user_id: str,
    ) -> WeaponDetail:
        try:
            from ...utils import dna_api

            response = await dna_api.get_weapon_detail(
                await self._legacy_user(actor, uid, credential_user_id),
                weapon_id,
                weapon_eid,
            )
            return self._weapon_detail(_response_data(response, resource="武器详情"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK, resource="武器详情"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(
                PlayerFailureKind.SERVER, resource="武器详情"
            ) from None

    @gated_transport_method
    async def calculate_damage(
        self,
        actor: EventActor,
        uid: str,
        role_detail: RoleDetail,
        con_weapon: WeaponDetail | None,
        close_weapon: WeaponDetail | None,
        ranged_weapon: WeaponDetail | None,
        *,
        credential_user_id: str,
    ) -> DamageCalculation:
        try:
            from ...modules.player.damage_service import (
                RoleDamageBuild,
                calculate_role_damage,
            )
            from ...utils.api.model import RoleDetail as LegacyRoleDetail
            from ...utils.api.model import WeaponDetail as LegacyWeaponDetail

            legacy_role = LegacyRoleDetail.model_validate(
                role_detail.model_dump(by_alias=True)
            )
            legacy_con = (
                None
                if con_weapon is None
                else LegacyWeaponDetail.model_validate(
                    con_weapon.model_dump(by_alias=True)
                )
            )
            legacy_close = (
                None
                if close_weapon is None
                else LegacyWeaponDetail.model_validate(
                    close_weapon.model_dump(by_alias=True)
                )
            )
            legacy_ranged = (
                None
                if ranged_weapon is None
                else LegacyWeaponDetail.model_validate(
                    ranged_weapon.model_dump(by_alias=True)
                )
            )
            response = await calculate_role_damage(
                await self._legacy_user(actor, uid, credential_user_id),
                RoleDamageBuild(
                    role_detail=legacy_role,
                    con_weapon_detail=legacy_con,
                    close_weapon_detail=legacy_close,
                    lang_range_weapon_detail=legacy_ranged,
                ),
            )
            if not response.is_success:
                if is_credential_failure(response):
                    raise PlayerTransportError(
                        PlayerFailureKind.CREDENTIAL,
                        resource="伤害计算",
                        detail=f"api response code={getattr(response, 'code', None)!r}",
                    )
                return DamageCalculation.failure(
                    response.msg or messages.PLAYER_DAMAGE_FAILED
                )
            if response.data is None:
                return DamageCalculation.failure(messages.PLAYER_DAMAGE_FAILED)
            return DamageCalculation.success(
                DamageSnapshot.model_validate(response.data.model_dump(by_alias=True)),
            )
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK, resource="伤害计算"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(
                PlayerFailureKind.SERVER, resource="伤害计算"
            ) from None


__all__ = ["DnaApiPlayerTransport"]
