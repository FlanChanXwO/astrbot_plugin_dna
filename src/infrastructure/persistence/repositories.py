"""面向 use case 的最小 repository 接口。

repository 只接收调用方明确传入的 ``AsyncSession``，不创建全局 session，也不在
内部偷偷提交事务。事务边界由 ``AsyncDatabase.transaction()`` 统一管理。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AccountBinding,
    CredentialRecord,
    GroupPrivacySetting,
    PrivacySetting,
    SignRecord,
)


class AccountBindingRepository:
    """账号绑定的读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        uid: str,
        group_id: str | None = None,
        is_active: bool = True,
    ) -> AccountBinding:
        record = AccountBinding(
            user_id=user_id,
            bot_id=bot_id,
            uid=uid,
            group_id=group_id,
            is_active=is_active,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> AccountBinding | None:
        statement = select(AccountBinding).where(
            AccountBinding.user_id == user_id,
            AccountBinding.bot_id == bot_id,
            AccountBinding.uid == uid,
        )
        return await session.scalar(statement)


class CredentialRepository:
    """凭据的读写入口；不会把敏感值写入日志或异常文本。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        uid: str,
        app_cookie: str = "",
        app_device_code: str = "",
        app_d_num: str = "",
        app_refresh_token: str = "",
        app_status: str = "",
        web_token: str = "",
        web_device_code: str = "",
        web_d_num: str = "",
        web_refresh_token: str = "",
        web_status: str = "",
    ) -> CredentialRecord:
        record = CredentialRecord(
            user_id=user_id,
            bot_id=bot_id,
            uid=uid,
            app_cookie=app_cookie,
            app_device_code=app_device_code,
            app_d_num=app_d_num,
            app_refresh_token=app_refresh_token,
            app_status=app_status,
            web_token=web_token,
            web_device_code=web_device_code,
            web_d_num=web_d_num,
            web_refresh_token=web_refresh_token,
            web_status=web_status,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> CredentialRecord | None:
        statement = select(CredentialRecord).where(
            CredentialRecord.user_id == user_id,
            CredentialRecord.bot_id == bot_id,
            CredentialRecord.uid == uid,
        )
        return await session.scalar(statement)


class SignRecordRepository:
    """签到状态的基础读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        uid: str,
        record_date: date,
        game_sign: int = 0,
        bbs_sign: int = 0,
        bbs_detail: int = 0,
        bbs_like: int = 0,
        bbs_share: int = 0,
        bbs_reply: int = 0,
    ) -> SignRecord:
        record = SignRecord(
            uid=uid,
            date=record_date,
            game_sign=game_sign,
            bbs_sign=bbs_sign,
            bbs_detail=bbs_detail,
            bbs_like=bbs_like,
            bbs_share=bbs_share,
            bbs_reply=bbs_reply,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        uid: str,
        record_date: date,
    ) -> SignRecord | None:
        statement = select(SignRecord).where(
            SignRecord.uid == uid,
            SignRecord.date == record_date,
        )
        return await session.scalar(statement)


class PrivacySettingRepository:
    """个人隐私设置的基础读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        group_id: str | None = None,
        allow_peek: bool = True,
        uid_hidden: bool = False,
    ) -> PrivacySetting:
        record = PrivacySetting(
            user_id=user_id,
            bot_id=bot_id,
            group_id=group_id,
            allow_peek=allow_peek,
            uid_hidden=uid_hidden,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        group_id: str | None = None,
    ) -> PrivacySetting | None:
        statement = select(PrivacySetting).where(
            PrivacySetting.user_id == user_id,
            PrivacySetting.bot_id == bot_id,
        )
        statement = statement.where(
            PrivacySetting.group_id.is_(None)
            if group_id is None
            else PrivacySetting.group_id == group_id
        )
        return await session.scalar(statement)


class GroupPrivacySettingRepository:
    """群组隐私设置的基础读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        group_id: str,
        bot_id: str,
        force_allow_peek: bool | None = None,
        force_uid_hidden: bool | None = None,
    ) -> GroupPrivacySetting:
        record = GroupPrivacySetting(
            group_id=group_id,
            bot_id=bot_id,
            force_allow_peek=force_allow_peek,
            force_uid_hidden=force_uid_hidden,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        group_id: str,
        bot_id: str,
    ) -> GroupPrivacySetting | None:
        statement = select(GroupPrivacySetting).where(
            GroupPrivacySetting.group_id == group_id,
            GroupPrivacySetting.bot_id == bot_id,
        )
        return await session.scalar(statement)


__all__ = [
    "AccountBindingRepository",
    "CredentialRepository",
    "GroupPrivacySettingRepository",
    "PrivacySettingRepository",
    "SignRecordRepository",
]
