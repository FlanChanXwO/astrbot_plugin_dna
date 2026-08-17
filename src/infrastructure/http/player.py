"""玩家查询的 legacy 纯 API 适配器。

只在 transport 边界读取 rewrite 凭据并组装 legacy ``DNAUser`` 值对象；业务层
收到的始终是 typed player contracts。没有账号凭据或外部 API 结构异常时，返回
安全的 ``PlayerTransportError``，不把原始响应或 secret 带进日志/响应。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from ...entry.event import EventActor
from ...infrastructure.persistence import AsyncDatabase, CredentialRepository
from ...modules.player.contracts import (
    DamageCalculation,
    DamageSnapshot,
    PlayerFailureKind,
    PlayerTransportError,
    RoleDetail,
    RoleOverview,
    WeaponDetail,
)


def _error_kind(response: Any) -> PlayerFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return PlayerFailureKind.NETWORK
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


class DnaApiPlayerTransport:
    """用已保存凭据调用 legacy 纯 API 方法的读取 transport。"""

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
            raise PlayerTransportError(
                PlayerFailureKind.SERVER,
                resource="账号凭据",
                detail="credential record is missing",
            )
        try:
            from dnaby.utils.database.models import DNAUser

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
            raise PlayerTransportError(
                PlayerFailureKind.SERVER,
                resource="账号凭据",
                detail=f"legacy credential value construction failed: {type(error).__name__}",
            ) from None

    @staticmethod
    def _overview(data: Any) -> RoleOverview:
        from dnaby.utils.api.model import DNARoleForToolRes

        payload = DNARoleForToolRes.model_validate(data)
        role_show = payload.roleInfo.roleShow
        return RoleOverview.model_validate(
            {
                "roleId": role_show.roleId,
                "roleName": role_show.roleName or "",
                "level": role_show.level,
                "params": [item.model_dump(by_alias=True) for item in role_show.params],
                "achievementTotal": role_show.roleAchv.total,
                "roleChars": [item.model_dump(by_alias=True) for item in role_show.roleChars],
                "langRangeWeapons": [
                    item.model_dump(by_alias=True) for item in role_show.langRangeWeapons
                ],
                "closeWeapons": [item.model_dump(by_alias=True) for item in role_show.closeWeapons],
            },
        )

    @staticmethod
    def _role_detail(data: Any) -> RoleDetail:
        from dnaby.utils.api.model import DNARoleDetailRes

        payload = DNARoleDetailRes.model_validate(data)
        return RoleDetail.model_validate(payload.charDetail.model_dump(by_alias=True))

    @staticmethod
    def _weapon_detail(data: Any) -> WeaponDetail:
        from dnaby.utils.api.model import DNAWeaponDetailRes

        payload = DNAWeaponDetailRes.model_validate(data)
        return WeaponDetail.model_validate(payload.weaponDetail.model_dump(by_alias=True))

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        try:
            from dnaby.utils import dna_api

            response = await dna_api.get_default_role_for_tool(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._overview(_response_data(response, resource="角色列表信息"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(PlayerFailureKind.NETWORK, resource="角色列表信息") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="角色列表信息") from None

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
            from dnaby.utils import dna_api

            response = await dna_api.get_role_detail(
                await self._legacy_user(actor, uid, credential_user_id),
                str(char_id),
                char_eid,
            )
            return self._role_detail(_response_data(response, resource="角色详情"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(PlayerFailureKind.NETWORK, resource="角色详情") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="角色详情") from None

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
            from dnaby.utils import dna_api

            response = await dna_api.get_weapon_detail(
                await self._legacy_user(actor, uid, credential_user_id),
                weapon_id,
                weapon_eid,
            )
            return self._weapon_detail(_response_data(response, resource="武器详情"))
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(PlayerFailureKind.NETWORK, resource="武器详情") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="武器详情") from None

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
            from dnaby.dna_detail.damage_service import (
                RoleDamageBuild,
                calculate_role_damage,
            )
            from dnaby.utils.api.model import RoleDetail as LegacyRoleDetail
            from dnaby.utils.api.model import WeaponDetail as LegacyWeaponDetail

            legacy_role = LegacyRoleDetail.model_validate(role_detail.model_dump(by_alias=True))
            legacy_con = (
                None
                if con_weapon is None
                else LegacyWeaponDetail.model_validate(con_weapon.model_dump(by_alias=True))
            )
            legacy_close = (
                None
                if close_weapon is None
                else LegacyWeaponDetail.model_validate(close_weapon.model_dump(by_alias=True))
            )
            legacy_ranged = (
                None
                if ranged_weapon is None
                else LegacyWeaponDetail.model_validate(ranged_weapon.model_dump(by_alias=True))
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
                return DamageCalculation.failure(response.msg or "伤害计算服务响应异常")
            if response.data is None:
                return DamageCalculation.failure("伤害计算服务响应异常")
            return DamageCalculation.success(
                DamageSnapshot.model_validate(response.data.model_dump(by_alias=True)),
            )
        except PlayerTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PlayerTransportError(PlayerFailureKind.NETWORK, resource="伤害计算") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise PlayerTransportError(PlayerFailureKind.SERVER, resource="伤害计算") from None


__all__ = ["DnaApiPlayerTransport"]
