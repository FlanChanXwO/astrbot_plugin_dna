"""个人/群组隐私策略和命令 use case。"""

from __future__ import annotations

from ...entry.response import PlainTextResponse
from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    GroupPrivacySettingRepository,
    PrivacySettingRepository,
)
from . import messages
from .contracts import PrivacyActor, PrivacySnapshot, QueryResolution


class PrivacyService:
    """在显式事务内协调个人隐私、群强制设置和 @ 查询策略。"""

    def __init__(self, database: AsyncDatabase, *, allow_mention_query: bool = True) -> None:
        self.database = database
        self.allow_mention_query = allow_mention_query

    async def get_privacy_setting(
        self,
        user_id: str,
        group_id: str | None = None,
    ) -> PrivacySnapshot:
        """读取指定作用域的个人设置；群组作用域缺失时回退全局个人值。"""

        async with self.database.session() as session:
            record = await PrivacySettingRepository.get(
                session,
                user_id=user_id,
                group_id=group_id,
            )
            if record is None and group_id is not None:
                record = await PrivacySettingRepository.get(
                    session,
                    user_id=user_id,
                    group_id=None,
                )
        if record is None:
            return PrivacySnapshot(allow_peek=True, uid_hidden=False)
        return PrivacySnapshot(
            allow_peek=record.allow_peek,
            uid_hidden=record.uid_hidden,
        )

    async def is_peek_allowed(
        self,
        user_id: str,
        group_id: str | None = None,
    ) -> bool:
        """判断目标是否允许被查看；群强制值优先于个人全局设置。"""

        async with self.database.session() as session:
            if group_id:
                group = await GroupPrivacySettingRepository.get(
                    session,
                    group_id=group_id,
                )
                if group is not None and group.force_allow_peek is not None:
                    return group.force_allow_peek

            personal = await self._personal_record(
                session,
                user_id=user_id,
                group_id=group_id,
            )
        return True if personal is None else personal.allow_peek

    async def is_uid_hidden(
        self,
        user_id: str,
        group_id: str | None = None,
    ) -> bool:
        """判断目标 UID 是否应隐藏；群强制值优先于个人全局设置。"""

        async with self.database.session() as session:
            if group_id:
                group = await GroupPrivacySettingRepository.get(
                    session,
                    group_id=group_id,
                )
                if group is not None and group.force_uid_hidden is not None:
                    return group.force_uid_hidden

            personal = await self._personal_record(
                session,
                user_id=user_id,
                group_id=group_id,
            )
        return False if personal is None else personal.uid_hidden

    async def resolve_query(
        self,
        actor: PrivacyActor,
        target_user_id: str | None,
    ) -> QueryResolution:
        """按 AT 查询配置、群强制值和目标个人设置解析最终用户。"""

        if not target_user_id or target_user_id == actor.user_id:
            return QueryResolution(target_user_id, actor.user_id, blocked=False)
        if not self.allow_mention_query:
            return QueryResolution(target_user_id, actor.user_id, blocked=True)
        if not await self.is_peek_allowed(
            target_user_id,
            actor.group_id,
        ):
            return QueryResolution(target_user_id, actor.user_id, blocked=True)
        return QueryResolution(target_user_id, target_user_id, blocked=False)

    async def set_personal_peek(
        self,
        actor: PrivacyActor,
        allow_peek: bool,
    ) -> PlainTextResponse:
        """设置调用者的全局个人偷窥开关。"""

        async with self.database.transaction() as session:
            blocked = await self._personal_force_message(
                session,
                actor,
                field="peek",
            )
            if blocked is not None:
                return PlainTextResponse(blocked)
            await PrivacySettingRepository.set(
                session,
                user_id=actor.user_id,
                group_id=None,
                allow_peek=allow_peek,
            )
        return PlainTextResponse(
            messages.PERSONAL_PEEK_ENABLED
            if allow_peek
            else messages.PERSONAL_PEEK_DISABLED,
        )

    async def set_personal_uid_hidden(
        self,
        actor: PrivacyActor,
        uid_hidden: bool,
    ) -> PlainTextResponse:
        """设置调用者的全局个人 UID 显示开关。"""

        async with self.database.transaction() as session:
            blocked = await self._personal_force_message(
                session,
                actor,
                field="uid",
            )
            if blocked is not None:
                return PlainTextResponse(blocked)
            await PrivacySettingRepository.set(
                session,
                user_id=actor.user_id,
                group_id=None,
                uid_hidden=uid_hidden,
            )
        return PlainTextResponse(
            messages.PERSONAL_UID_ENABLED
            if uid_hidden
            else messages.PERSONAL_UID_DISABLED,
        )

    async def set_target_peek(
        self,
        actor: PrivacyActor,
        target_user_id: str | None,
        allow_peek: bool,
    ) -> PlainTextResponse:
        """由群管理员设置被 @ 用户的全局偷窥开关。"""

        missing_target = (
            messages.TARGET_PEEK_ENABLE_REQUIRED
            if allow_peek
            else messages.TARGET_PEEK_DISABLE_REQUIRED
        )
        async with self.database.transaction() as session:
            group_error = self._require_group(actor)
            if group_error is not None:
                return PlainTextResponse(group_error)
            blocked = await self._personal_force_message(
                session,
                actor,
                field="peek",
            )
            if blocked is not None:
                return PlainTextResponse(blocked)
            if target_user_id is None:
                return PlainTextResponse(missing_target)
            if not await AccountBindingRepository.exists(
                session,
                user_id=target_user_id,
            ):
                return PlainTextResponse(messages.TARGET_NOT_BOUND)
            await PrivacySettingRepository.set(
                session,
                user_id=target_user_id,
                group_id=None,
                allow_peek=allow_peek,
            )
        return PlainTextResponse(
            messages.TARGET_PEEK_ENABLED
            if allow_peek
            else messages.TARGET_PEEK_DISABLED,
        )

    async def set_target_uid_hidden(
        self,
        actor: PrivacyActor,
        target_user_id: str | None,
        uid_hidden: bool,
    ) -> PlainTextResponse:
        """由群管理员设置被 @ 用户的全局 UID 显示开关。"""

        missing_target = (
            messages.TARGET_UID_ENABLE_REQUIRED
            if uid_hidden
            else messages.TARGET_UID_DISABLE_REQUIRED
        )
        async with self.database.transaction() as session:
            group_error = self._require_group(actor)
            if group_error is not None:
                return PlainTextResponse(group_error)
            blocked = await self._personal_force_message(
                session,
                actor,
                field="uid",
            )
            if blocked is not None:
                return PlainTextResponse(blocked)
            if target_user_id is None:
                return PlainTextResponse(missing_target)
            if not await AccountBindingRepository.exists(
                session,
                user_id=target_user_id,
            ):
                return PlainTextResponse(messages.TARGET_NOT_BOUND)
            await PrivacySettingRepository.set(
                session,
                user_id=target_user_id,
                group_id=None,
                uid_hidden=uid_hidden,
            )
        return PlainTextResponse(
            messages.TARGET_UID_ENABLED
            if uid_hidden
            else messages.TARGET_UID_DISABLED,
        )

    async def set_group_peek(
        self,
        actor: PrivacyActor,
        force_allow_peek: bool,
    ) -> PlainTextResponse:
        """设置当前群的全体偷窥强制值。"""

        group_error = self._require_group(actor)
        if group_error is not None:
            return PlainTextResponse(group_error)
        group_id = actor.group_id
        assert group_id is not None
        async with self.database.transaction() as session:
            await GroupPrivacySettingRepository.set(
                session,
                group_id=group_id,
                force_allow_peek=force_allow_peek,
            )
        return PlainTextResponse(
            messages.GROUP_PEEK_ENABLED
            if force_allow_peek
            else messages.GROUP_PEEK_DISABLED,
        )

    async def cancel_group_peek(self, actor: PrivacyActor) -> PlainTextResponse:
        """清除当前群的全体偷窥强制值。"""

        group_error = self._require_group(actor)
        if group_error is not None:
            return PlainTextResponse(group_error)
        group_id = actor.group_id
        assert group_id is not None
        async with self.database.transaction() as session:
            await GroupPrivacySettingRepository.set(
                session,
                group_id=group_id,
                force_allow_peek=None,
            )
        return PlainTextResponse(messages.GROUP_PEEK_CANCELLED)

    async def set_group_uid_hidden(
        self,
        actor: PrivacyActor,
        force_uid_hidden: bool,
    ) -> PlainTextResponse:
        """设置当前群的全体 UID 隐藏强制值。"""

        group_error = self._require_group(actor)
        if group_error is not None:
            return PlainTextResponse(group_error)
        group_id = actor.group_id
        assert group_id is not None
        async with self.database.transaction() as session:
            await GroupPrivacySettingRepository.set(
                session,
                group_id=group_id,
                force_uid_hidden=force_uid_hidden,
            )
        return PlainTextResponse(
            messages.GROUP_UID_ENABLED
            if force_uid_hidden
            else messages.GROUP_UID_DISABLED,
        )

    async def cancel_group_uid_hidden(self, actor: PrivacyActor) -> PlainTextResponse:
        """清除当前群的全体 UID 隐藏强制值。"""

        group_error = self._require_group(actor)
        if group_error is not None:
            return PlainTextResponse(group_error)
        group_id = actor.group_id
        assert group_id is not None
        async with self.database.transaction() as session:
            await GroupPrivacySettingRepository.set(
                session,
                group_id=group_id,
                force_uid_hidden=None,
            )
        return PlainTextResponse(messages.GROUP_UID_CANCELLED)

    @staticmethod
    def _require_group(actor: PrivacyActor) -> str | None:
        """返回群管理员命令所需的群聊错误。"""

        return None if actor.group_id else messages.GROUP_REQUIRED

    @staticmethod
    async def _personal_force_message(
        session,
        actor: PrivacyActor,
        *,
        field: str,
    ) -> str | None:
        """读取当前群的单字段强制值并转换为个人修改错误。"""

        if not actor.group_id:
            return None
        group = await GroupPrivacySettingRepository.get(
            session,
            group_id=actor.group_id,
        )
        if group is None:
            return None
        if field == "peek":
            value = group.force_allow_peek
            return None if value is None else messages.personal_peek_blocked(value)
        if field == "uid":
            value = group.force_uid_hidden
            return None if value is None else messages.personal_uid_blocked(value)
        raise ValueError(f"未知隐私字段: {field}")

    @staticmethod
    async def _personal_record(
        session,
        *,
        user_id: str,
        group_id: str | None,
    ):
        """按群组个人设置优先、全局个人设置回退读取记录。"""

        if group_id is not None:
            scoped = await PrivacySettingRepository.get(
                session,
                user_id=user_id,
                group_id=group_id,
            )
            if scoped is not None:
                return scoped
        return await PrivacySettingRepository.get(
            session,
            user_id=user_id,
            group_id=None,
        )


__all__ = ["PrivacyService"]
