"""框架无关的管理员账号管理 use case。"""

from __future__ import annotations

from typing import Any, cast

from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from ...infrastructure.persistence.models import AccountBinding, CredentialRecord

from .contracts import (
    CREDENTIAL_FIELDS,
    UNSET,
    AdminAccount,
    AdminAccountUpdate,
    AdminApiResponse,
    AdminError,
    AdminErrorCode,
    CredentialPayload,
    DeletionPreview,
)

_UID_DELETE_RESOURCES = (
    "account_binding",
    "credential_records",
    "sign_records",
)
_UID_PRESERVE_RESOURCES = (
    "other_account_bindings",
    "user_privacy",
    "personal_subscriptions",
    "group_privacy",
    "group_subscriptions",
    "group_results",
    "notice_assets",
)
_USER_DELETE_RESOURCES = (
    "account_bindings",
    "credential_records",
    "sign_records",
    "user_privacy",
    "personal_subscriptions",
)
_USER_PRESERVE_RESOURCES = (
    "other_account_bindings",
    "group_privacy",
    "group_subscriptions",
    "group_results",
    "notice_assets",
)


def _normalized_identity(value: str) -> str | None:
    """验证并规范管理请求中的 user_id/uid。"""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _failure(
    code: AdminErrorCode,
    message: str,
) -> AdminApiResponse[Any]:
    return AdminApiResponse.failure(AdminError(code, message))


def _payload_from_record(record: CredentialRecord) -> CredentialPayload:
    """将 ORM 凭据复制为仅供管理详情使用的明文 DTO。"""

    return CredentialPayload(
        app_cookie=record.app_cookie,
        app_device_code=record.app_device_code,
        app_d_num=record.app_d_num,
        app_refresh_token=record.app_refresh_token,
        app_status=record.app_status,
        web_token=record.web_token,
        web_device_code=record.web_device_code,
        web_d_num=record.web_d_num,
        web_refresh_token=record.web_refresh_token,
        web_status=record.web_status,
    )


def _account_from_records(
    binding: AccountBinding,
    credential: CredentialRecord | None,
    *,
    include_credentials: bool,
) -> AdminAccount:
    payload = _payload_from_record(credential) if credential is not None else None
    return AdminAccount(
        user_id=binding.user_id,
        uid=binding.uid,
        group_id=binding.group_id,
        is_active=binding.is_active,
        has_app_credentials=credential.has_app_credentials if credential else False,
        has_web_credentials=credential.has_web_credentials if credential else False,
        app_status=credential.app_status if credential else "",
        web_status=credential.web_status if credential else "",
        credentials=payload if include_credentials else None,
    )


class AdminAccountService:
    """提供账号列表、编辑和删除预览，不提供账号创建。"""

    def __init__(self, database: AsyncDatabase) -> None:
        self.database = database

    async def list_accounts(
        self,
        *,
        include_credentials: bool = False,
    ) -> AdminApiResponse[tuple[AdminAccount, ...]]:
        """列出全局账号；默认只返回凭据状态，明文需显式请求。"""

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list_all(session)
            accounts = []
            for binding in bindings:
                credential = await CredentialRepository.get(
                    session,
                    user_id=binding.user_id,
                    uid=binding.uid,
                )
                accounts.append(
                    _account_from_records(
                        binding,
                        credential,
                        include_credentials=include_credentials,
                    )
                )
        return AdminApiResponse.success(tuple(accounts))

    async def get_account(
        self,
        user_id: str,
        uid: str,
        *,
        include_credentials: bool = True,
    ) -> AdminApiResponse[AdminAccount]:
        """读取已有全局绑定；详情默认返回完整明文凭据。"""

        normalized_user_id = _normalized_identity(user_id)
        normalized_uid = _normalized_identity(uid)
        if normalized_user_id is None or normalized_uid is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 和 uid 不能为空")

        async with self.database.session() as session:
            binding = await AccountBindingRepository.get(
                session,
                user_id=normalized_user_id,
                uid=normalized_uid,
            )
            if binding is None:
                return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")
            credential = await CredentialRepository.get(
                session,
                user_id=normalized_user_id,
                uid=normalized_uid,
            )
            account = _account_from_records(
                binding,
                credential,
                include_credentials=include_credentials,
            )
        return AdminApiResponse.success(account)

    async def update_account(
        self,
        user_id: str,
        uid: str,
        update: AdminAccountUpdate,
    ) -> AdminApiResponse[AdminAccount]:
        """编辑已有绑定的来源群、active 和全部 App/Web 凭据。

        更新只允许命中已存在的 ``(user_id, uid)``；凭据记录可以在已有绑定上首次
        建立，但不会借此创建新的账号绑定。
        """

        if not isinstance(update, AdminAccountUpdate):
            return _failure(AdminErrorCode.VALIDATION, "更新请求类型错误")
        normalized_user_id = _normalized_identity(user_id)
        normalized_uid = _normalized_identity(uid)
        if normalized_user_id is None or normalized_uid is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 和 uid 不能为空")

        if update.user_id is not None and (
            _normalized_identity(update.user_id) != normalized_user_id
        ):
            return _failure(AdminErrorCode.CONFLICT, "user_id 是只读身份键")
        if update.uid is not None and _normalized_identity(update.uid) != normalized_uid:
            return _failure(AdminErrorCode.CONFLICT, "uid 是只读身份键")

        async with self.database.transaction() as session:
            binding = await AccountBindingRepository.get(
                session,
                user_id=normalized_user_id,
                uid=normalized_uid,
            )
            if binding is None:
                return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")

            if update.group_id is not UNSET:
                binding.group_id = update.group_id

            if update.is_active is not UNSET:
                if update.is_active:
                    switched = await AccountBindingRepository.set_active(
                        session,
                        user_id=normalized_user_id,
                        uid=normalized_uid,
                    )
                    if not switched:
                        return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")
                else:
                    binding.is_active = False
                    await session.flush()

            if update.credentials is not UNSET:
                await self._replace_credentials(
                    session,
                    user_id=normalized_user_id,
                    uid=normalized_uid,
                    payload=cast(CredentialPayload, update.credentials),
                )

            await session.flush()
            credential = await CredentialRepository.get(
                session,
                user_id=normalized_user_id,
                uid=normalized_uid,
            )
            account = _account_from_records(
                binding,
                credential,
                include_credentials=True,
            )
        return AdminApiResponse.success(account)

    async def _replace_credentials(
        self,
        session,
        *,
        user_id: str,
        uid: str,
        payload: CredentialPayload,
    ) -> CredentialRecord:
        """在已有绑定内原子替换十个凭据字段。"""

        record = await CredentialRepository.get(
            session,
            user_id=user_id,
            uid=uid,
        )
        if record is None:
            return await CredentialRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                **payload.to_plaintext_dict(),
            )

        values = payload.to_plaintext_dict()
        for field_name in CREDENTIAL_FIELDS:
            setattr(record, field_name, values[field_name])
        await session.flush()
        return record

    async def preview_delete_uid(
        self,
        user_id: str,
        uid: str,
    ) -> AdminApiResponse[DeletionPreview]:
        """预览删除一个 UID 的影响，不执行删除。"""

        normalized_user_id = _normalized_identity(user_id)
        normalized_uid = _normalized_identity(uid)
        if normalized_user_id is None or normalized_uid is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 和 uid 不能为空")

        async with self.database.session() as session:
            binding = await AccountBindingRepository.get(
                session,
                user_id=normalized_user_id,
                uid=normalized_uid,
            )
        if binding is None:
            return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")

        preview = DeletionPreview(
            user_id=normalized_user_id,
            uid=normalized_uid,
            affected_uids=(normalized_uid,),
            delete_resources=_UID_DELETE_RESOURCES,
            preserve_resources=_UID_PRESERVE_RESOURCES,
            confirmation_payload=f"delete:uid:{normalized_user_id}:{normalized_uid}",
        )
        return AdminApiResponse.success(preview)

    async def preview_delete_user(
        self,
        user_id: str,
    ) -> AdminApiResponse[DeletionPreview]:
        """预览删除用户全部 UID 的影响，不执行删除。"""

        normalized_user_id = _normalized_identity(user_id)
        if normalized_user_id is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 不能为空")

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list(
                session,
                user_id=normalized_user_id,
            )
        if not bindings:
            return _failure(AdminErrorCode.NOT_FOUND, "用户没有账号绑定")

        preview = DeletionPreview(
            user_id=normalized_user_id,
            uid=None,
            affected_uids=tuple(binding.uid for binding in bindings),
            delete_resources=_USER_DELETE_RESOURCES,
            preserve_resources=_USER_PRESERVE_RESOURCES,
            confirmation_payload=f"delete:user:{normalized_user_id}",
        )
        return AdminApiResponse.success(preview)


__all__ = ["AdminAccountService"]
