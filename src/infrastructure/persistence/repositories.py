"""面向 use case 的最小 repository 接口。

repository 只接收调用方明确传入的 ``AsyncSession``，不创建全局 session，也不在
内部偷偷提交事务。事务边界由 ``AsyncDatabase.transaction()`` 统一管理。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import cast

from sqlalchemy import delete, select, update
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
        uid: str,
        group_id: str | None = None,
        is_active: bool = True,
        auto_sign_enabled: bool = True,
    ) -> AccountBinding:
        record = AccountBinding(
            user_id=user_id,
            uid=uid,
            group_id=group_id,
            is_active=is_active,
            auto_sign_enabled=auto_sign_enabled,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> AccountBinding | None:
        statement = select(AccountBinding).where(
            AccountBinding.user_id == user_id,
            AccountBinding.uid == uid,
        )
        return await session.scalar(statement)

    @staticmethod
    async def exists(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> bool:
        """检查用户是否有任意 UID 绑定，不把目标 UID 暴露给调用方。"""

        statement = (
            select(AccountBinding.id)
            .where(
                AccountBinding.user_id == user_id,
            )
            .limit(1)
        )
        return (await session.scalar(statement)) is not None

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> list[AccountBinding]:
        """按绑定建立顺序返回一个用户的全部 UID。"""
        statement = (
            select(AccountBinding)
            .where(
                AccountBinding.user_id == user_id,
            )
            .order_by(AccountBinding.id)
        )
        return list((await session.scalars(statement)).all())

    @staticmethod
    async def list_all(
        session: AsyncSession,
    ) -> list[AccountBinding]:
        """返回全部全局绑定；供批量签到读取，不在此处暴露凭据。"""
        statement = select(AccountBinding)
        statement = statement.order_by(AccountBinding.id)
        return list((await session.scalars(statement)).all())

    @staticmethod
    async def list_auto_sign_candidates(
        session: AsyncSession,
    ) -> list[AccountBinding]:
        """返回具备可用 App 凭据且开启自动签到的绑定。

        只按非敏感状态筛选，不读取或返回任何凭据值。缺失凭据、已标记无效、
        token/device code 为空的历史绑定不会进入计划任务，也不会被计为群签到失败。
        """

        statement = (
            select(AccountBinding)
            .join(
                CredentialRecord,
                (CredentialRecord.user_id == AccountBinding.user_id)
                & (CredentialRecord.uid == AccountBinding.uid),
            )
            .where(
                AccountBinding.auto_sign_enabled.is_(True),
                CredentialRecord.app_status != "无效",
                CredentialRecord.app_cookie != "",
                CredentialRecord.app_device_code != "",
            )
            .order_by(AccountBinding.id)
        )
        return list((await session.scalars(statement)).all())

    @staticmethod
    async def current(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> AccountBinding | None:
        """返回用户当前 active UID；数据异常时按最新记录确定性选择。"""
        statement = (
            select(AccountBinding)
            .where(
                AccountBinding.user_id == user_id,
                AccountBinding.is_active.is_(True),
            )
            .order_by(AccountBinding.id.desc())
        )
        return await session.scalar(statement)

    @staticmethod
    async def set_active(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> bool:
        """在同一 session 中保证一个用户只有一个当前 UID。"""
        records = await AccountBindingRepository.list(
            session,
            user_id=user_id,
        )
        target = next((record for record in records if record.uid == uid), None)
        if target is None:
            return False
        await session.execute(
            update(AccountBinding)
            .where(AccountBinding.user_id == user_id)
            .values(is_active=False)
        )
        target.is_active = True
        await session.flush()
        return True

    @staticmethod
    async def set_auto_sign_enabled(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
        enabled: bool,
    ) -> bool:
        """按用户和 UID 独立切换自动签到状态。"""

        result = await session.execute(
            update(AccountBinding)
            .where(
                AccountBinding.user_id == user_id,
                AccountBinding.uid == uid,
            )
            .values(auto_sign_enabled=enabled)
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    async def delete(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> bool:
        """删除一个 UID 绑定，并显式返回是否命中记录。"""
        record = await AccountBindingRepository.get(
            session,
            user_id=user_id,
            uid=uid,
        )
        if record is None:
            return False
        await session.delete(record)
        await session.flush()
        return True

    @staticmethod
    async def delete_all(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> int:
        """删除一个用户的全部绑定。"""
        result = await session.execute(
            delete(AccountBinding).where(
                AccountBinding.user_id == user_id,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)


class CredentialRepository:
    """凭据的读写入口；不会把敏感值写入日志或异常文本。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
        app_cookie: str = "",
        app_device_code: str = "",
        app_d_num: str = "",
        app_refresh_token: str = "",
        app_status: str = "",
    ) -> CredentialRecord:
        record = CredentialRecord(
            user_id=user_id,
            uid=uid,
            app_cookie=app_cookie,
            app_device_code=app_device_code,
            app_d_num=app_d_num,
            app_refresh_token=app_refresh_token,
            app_status=app_status,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> CredentialRecord | None:
        statement = select(CredentialRecord).where(
            CredentialRecord.user_id == user_id,
            CredentialRecord.uid == uid,
        )
        return await session.scalar(statement)

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> list[CredentialRecord]:
        """按记录建立顺序返回凭据状态；调用方不得直接序列化 secret 字段。"""
        statement = (
            select(CredentialRecord)
            .where(
                CredentialRecord.user_id == user_id,
            )
            .order_by(CredentialRecord.id)
        )
        return list((await session.scalars(statement)).all())

    @staticmethod
    async def save_app(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
        token: str,
        device_code: str,
        d_num: str = "",
        refresh_token: str = "",
        status: str = "",
    ) -> CredentialRecord:
        """保存同一 UID 的 App 凭据。"""
        record = await CredentialRepository.get(
            session,
            user_id=user_id,
            uid=uid,
        )
        if record is None:
            record = await CredentialRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                app_cookie=token,
                app_device_code=device_code,
                app_d_num=d_num,
                app_refresh_token=refresh_token,
                app_status=status,
            )
            return record
        record.app_cookie = token
        record.app_device_code = device_code
        record.app_d_num = d_num
        record.app_refresh_token = refresh_token
        record.app_status = status
        await session.flush()
        return record

    @staticmethod
    async def mark_app_invalid(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> bool:
        """把已被上游明确判定失效的 App 凭据持久化为无效状态。"""

        result = await session.execute(
            update(CredentialRecord)
            .where(
                CredentialRecord.user_id == user_id,
                CredentialRecord.uid == uid,
            )
            .values(app_status="无效")
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    async def delete(
        session: AsyncSession,
        *,
        user_id: str,
        uid: str,
    ) -> bool:
        """删除一个 UID 的全部凭据。"""
        record = await CredentialRepository.get(
            session,
            user_id=user_id,
            uid=uid,
        )
        if record is None:
            return False
        await session.delete(record)
        await session.flush()
        return True

    @staticmethod
    async def delete_all(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> int:
        """删除一个用户的全部 App 凭据。"""

        result = await session.execute(
            delete(CredentialRecord).where(
                CredentialRecord.user_id == user_id,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)


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

    @staticmethod
    async def save(
        session: AsyncSession,
        *,
        uid: str,
        record_date: date,
        game_sign: int,
        bbs_sign: int,
        bbs_detail: int,
        bbs_like: int,
        bbs_share: int,
        bbs_reply: int,
    ) -> SignRecord:
        """按 UID+日期 upsert 当天签到计数，返回持久化记录。"""
        record = await SignRecordRepository.get(
            session,
            uid=uid,
            record_date=record_date,
        )
        if record is None:
            return await SignRecordRepository.add(
                session,
                uid=uid,
                record_date=record_date,
                game_sign=game_sign,
                bbs_sign=bbs_sign,
                bbs_detail=bbs_detail,
                bbs_like=bbs_like,
                bbs_share=bbs_share,
                bbs_reply=bbs_reply,
            )
        record.game_sign = game_sign
        record.bbs_sign = bbs_sign
        record.bbs_detail = bbs_detail
        record.bbs_like = bbs_like
        record.bbs_share = bbs_share
        record.bbs_reply = bbs_reply
        await session.flush()
        return record

    @staticmethod
    async def delete_before(
        session: AsyncSession,
        record_date: date,
    ) -> int:
        """删除指定日期（不含）之前的签到记录，返回删除条数。"""
        result = await session.execute(
            delete(SignRecord).where(SignRecord.date < record_date)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    async def delete_for_uids(
        session: AsyncSession,
        uids: Iterable[str],
    ) -> int:
        """删除一组 UID 的全部签到历史，供用户级联删除强制清理。"""

        unique_uids = tuple(dict.fromkeys(uids))
        if not unique_uids:
            return 0
        result = await session.execute(
            delete(SignRecord).where(SignRecord.uid.in_(unique_uids))
        )
        return int(getattr(result, "rowcount", 0) or 0)


class PrivacySettingRepository:
    """个人隐私设置的基础读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        user_id: str,
        group_id: str | None = None,
        allow_peek: bool = True,
        uid_hidden: bool = False,
    ) -> PrivacySetting:
        record = PrivacySetting(
            user_id=user_id,
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
        group_id: str | None = None,
    ) -> PrivacySetting | None:
        statement = select(PrivacySetting).where(
            PrivacySetting.user_id == user_id,
        )
        statement = statement.where(
            PrivacySetting.group_id.is_(None)
            if group_id is None
            else PrivacySetting.group_id == group_id
        )
        statement = statement.order_by(PrivacySetting.id.desc())
        return await session.scalar(statement)

    @staticmethod
    async def set(
        session: AsyncSession,
        *,
        user_id: str,
        group_id: str | None = None,
        allow_peek: bool | None = None,
        uid_hidden: bool | None = None,
    ) -> PrivacySetting:
        """按作用域更新设置；``None`` 字段表示保留已有值。"""

        record = await PrivacySettingRepository.get(
            session,
            user_id=user_id,
            group_id=group_id,
        )
        if record is None:
            return await PrivacySettingRepository.add(
                session,
                user_id=user_id,
                group_id=group_id,
                allow_peek=True if allow_peek is None else allow_peek,
                uid_hidden=False if uid_hidden is None else uid_hidden,
            )

        if allow_peek is not None:
            record.allow_peek = allow_peek
        if uid_hidden is not None:
            record.uid_hidden = uid_hidden
        await session.flush()
        return record

    @staticmethod
    async def delete_all(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> int:
        """删除一个用户的全局及个人群组隐私设置，不触碰群强制设置。"""

        result = await session.execute(
            delete(PrivacySetting).where(
                PrivacySetting.user_id == user_id,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)


_NO_CHANGE = object()


class GroupPrivacySettingRepository:
    """群组隐私设置的基础读写入口。"""

    @staticmethod
    async def add(
        session: AsyncSession,
        *,
        group_id: str,
        force_allow_peek: bool | None = None,
        force_uid_hidden: bool | None = None,
    ) -> GroupPrivacySetting:
        record = GroupPrivacySetting(
            group_id=group_id,
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
    ) -> GroupPrivacySetting | None:
        statement = select(GroupPrivacySetting).where(
            GroupPrivacySetting.group_id == group_id,
        )
        return await session.scalar(statement)

    @staticmethod
    async def set(
        session: AsyncSession,
        *,
        group_id: str,
        force_allow_peek: bool | None | object = _NO_CHANGE,
        force_uid_hidden: bool | None | object = _NO_CHANGE,
    ) -> GroupPrivacySetting:
        """按字段更新群强制策略；传入 ``None`` 会清除对应强制值。"""

        record = await GroupPrivacySettingRepository.get(
            session,
            group_id=group_id,
        )
        if record is None:
            record = await GroupPrivacySettingRepository.add(
                session,
                group_id=group_id,
                force_allow_peek=cast(
                    bool | None,
                    None if force_allow_peek is _NO_CHANGE else force_allow_peek,
                ),
                force_uid_hidden=cast(
                    bool | None,
                    None if force_uid_hidden is _NO_CHANGE else force_uid_hidden,
                ),
            )
            return record

        if force_allow_peek is not _NO_CHANGE:
            record.force_allow_peek = cast(bool | None, force_allow_peek)
        if force_uid_hidden is not _NO_CHANGE:
            record.force_uid_hidden = cast(bool | None, force_uid_hidden)
        await session.flush()
        return record


__all__ = [
    "AccountBindingRepository",
    "CredentialRepository",
    "GroupPrivacySettingRepository",
    "PrivacySettingRepository",
    "SignRecordRepository",
]
