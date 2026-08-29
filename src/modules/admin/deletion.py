"""管理员账号级联删除的预览、执行与可重试协调。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
    PrivacySettingRepository,
    SignRecordRepository,
)
from ...infrastructure.subscriptions import SubscriptionStore
from ..notices import messages as notices_messages
from .contracts import (
    AdminApiResponse,
    AdminError,
    AdminErrorCode,
    DeletionExecution,
    DeletionExecutionStatus,
    DeletionPreview,
    DeletionStepResult,
    DeletionStepStatus,
)
from .service import AdminAccountService

_DeletionScope = Literal["uid", "user"]

_UID_DATABASE_RESOURCES = (
    "account_binding",
    "credential_records",
    "sign_records",
)
_USER_DATABASE_RESOURCES = (
    "account_bindings",
    "credential_records",
    "user_privacy",
    "sign_records",
)
_GROUP_PRESERVED_RESOURCES = (
    "group_privacy",
    "group_subscriptions",
    "group_results",
    "notice_assets",
)


@dataclass(frozen=True, slots=True)
class _DatabaseDeletion:
    """SQLite 事务结果；失败时整个事务已经回滚。"""

    committed: bool
    steps: tuple[DeletionStepResult, ...]


def _counted_step(resource: str, count: int) -> DeletionStepResult:
    return DeletionStepResult(
        resource=resource,
        status=(
            DeletionStepStatus.DELETED
            if count > 0
            else DeletionStepStatus.ALREADY_ABSENT
        ),
        count=count,
    )


def _preserved_step(resource: str) -> DeletionStepResult:
    return DeletionStepResult(
        resource=resource,
        status=DeletionStepStatus.PRESERVED,
        message="未纳入本次用户级联删除",
    )


def _failed_step(resource: str) -> DeletionStepResult:
    return DeletionStepResult(
        resource=resource,
        status=DeletionStepStatus.FAILED,
        message="存储步骤失败，可使用同一删除计划重试",
    )


def _skipped_step(resource: str) -> DeletionStepResult:
    return DeletionStepResult(
        resource=resource,
        status=DeletionStepStatus.SKIPPED,
        message="SQLite 删除失败，尚未执行该 JSON 步骤",
    )


def _validation_error(message: str) -> AdminApiResponse[DeletionExecution]:
    return AdminApiResponse.failure(AdminError(AdminErrorCode.VALIDATION, message))


def _validate_plan(
    plan: DeletionPreview,
    confirmation_payload: str,
    *,
    scope: _DeletionScope,
) -> str | AdminApiResponse[DeletionExecution]:
    """验证计划和确认串的身份绑定，确保执行前不产生任何副作用。"""

    if not isinstance(plan, DeletionPreview):
        return _validation_error("删除计划类型错误")
    if not isinstance(plan.user_id, str) or not plan.user_id.strip():
        return _validation_error("删除计划缺少 user_id")
    if plan.user_id != plan.user_id.strip():
        return _validation_error("删除计划 user_id 未规范化")

    if scope == "uid":
        if not isinstance(plan.uid, str) or not plan.uid:
            return _validation_error("UID 删除计划缺少 uid")
        expected = f"delete:uid:{plan.user_id}:{plan.uid}"
        if plan.affected_uids != (plan.uid,):
            return _validation_error("UID 删除计划范围不一致")
    else:
        if plan.uid is not None or not plan.affected_uids:
            return _validation_error("用户删除计划范围不一致")
        if any(
            not isinstance(uid, str) or not uid or uid != uid.strip()
            for uid in plan.affected_uids
        ):
            return _validation_error("用户删除计划包含无效 UID")
        if len(set(plan.affected_uids)) != len(plan.affected_uids):
            return _validation_error("用户删除计划包含重复 UID")
        expected = f"delete:user:{plan.user_id}"

    if plan.confirmation_payload != expected or confirmation_payload != expected:
        return _validation_error("删除确认串与目标身份不匹配")
    return plan.user_id


class AccountDeletionCoordinator:
    """串行协调 SQLite 与 JSON 的用户/UID 级联删除。

    SQLite 步骤先在单事务中完成；只有事务提交后才修改订阅 JSON。两种存储无法
    共享物理事务，因此每一步都报告状态，JSON 失败时保留可用的原删除计划供重试。
    """

    def __init__(
        self,
        database: AsyncDatabase,
        subscriptions: SubscriptionStore | None = None,
    ) -> None:
        self.database = database
        self.subscriptions = subscriptions
        self._accounts = AdminAccountService(database)

    async def preview_delete_uid(
        self,
        user_id: str,
        uid: str,
    ) -> AdminApiResponse[DeletionPreview]:
        """返回单 UID 删除计划。"""

        return await self._accounts.preview_delete_uid(user_id, uid)

    async def preview_delete_user(
        self,
        user_id: str,
    ) -> AdminApiResponse[DeletionPreview]:
        """返回用户全部 UID 删除计划。"""

        return await self._accounts.preview_delete_user(user_id)

    async def _delete_uid_database(
        self,
        plan: DeletionPreview,
    ) -> _DatabaseDeletion:
        try:
            async with self.database.transaction() as session:
                binding_count = int(
                    await AccountBindingRepository.delete(
                        session,
                        user_id=plan.user_id,
                        uid=plan.uid or "",
                    )
                )
                credential_count = int(
                    await CredentialRepository.delete(
                        session,
                        user_id=plan.user_id,
                        uid=plan.uid or "",
                    )
                )
                sign_count = await SignRecordRepository.delete_for_uids(
                    session,
                    plan.affected_uids,
                )
        except Exception:  # noqa: BLE001
            # 不把数据库异常原文带入管理响应；事务上下文已负责回滚。
            return _DatabaseDeletion(
                committed=False,
                steps=tuple(_failed_step(resource) for resource in _UID_DATABASE_RESOURCES),
            )
        return _DatabaseDeletion(
            committed=True,
            steps=(
                _counted_step("account_binding", binding_count),
                _counted_step("credential_records", credential_count),
                _counted_step("sign_records", sign_count),
            ),
        )

    async def _delete_user_database(
        self,
        plan: DeletionPreview,
    ) -> _DatabaseDeletion:
        try:
            async with self.database.transaction() as session:
                binding_count = await AccountBindingRepository.delete_all(
                    session,
                    user_id=plan.user_id,
                )
                credential_count = await CredentialRepository.delete_all(
                    session,
                    user_id=plan.user_id,
                )
                privacy_count = await PrivacySettingRepository.delete_all(
                    session,
                    user_id=plan.user_id,
                )
                sign_count = await SignRecordRepository.delete_for_uids(
                    session,
                    plan.affected_uids,
                )
        except Exception:  # noqa: BLE001
            # 不把数据库异常原文带入管理响应；事务上下文已负责回滚。
            return _DatabaseDeletion(
                committed=False,
                steps=tuple(_failed_step(resource) for resource in _USER_DATABASE_RESOURCES),
            )
        return _DatabaseDeletion(
            committed=True,
            steps=(
                _counted_step("account_bindings", binding_count),
                _counted_step("credential_records", credential_count),
                _counted_step("user_privacy", privacy_count),
                _counted_step("sign_records", sign_count),
            ),
        )

    async def _delete_personal_subscriptions(
        self,
        *,
        user_id: str,
        database_committed: bool,
    ) -> DeletionStepResult:
        if not database_committed:
            return _skipped_step("personal_subscriptions")
        if self.subscriptions is None:
            return DeletionStepResult(
                resource="personal_subscriptions",
                status=DeletionStepStatus.FAILED,
                message="订阅存储不可用，可使用同一删除计划重试",
            )
        try:
            count = await self.subscriptions.delete_personal_subscriptions(
                user_id,
                subscription_type=notices_messages.MH_SUBSCRIBE,
            )
        except Exception:  # noqa: BLE001
            # JSON 错误必须可观察但不能泄露路径、内容或异常原文。
            return DeletionStepResult(
                resource="personal_subscriptions",
                status=DeletionStepStatus.FAILED,
                message="订阅 JSON 步骤失败，可使用同一删除计划重试",
            )
        return _counted_step("personal_subscriptions", count)

    @staticmethod
    def _report(
        plan: DeletionPreview,
        steps: tuple[DeletionStepResult, ...],
        *,
        status: DeletionExecutionStatus,
    ) -> DeletionExecution:
        return DeletionExecution(
            user_id=plan.user_id,
            uid=plan.uid,
            affected_uids=plan.affected_uids,
            confirmation_payload=plan.confirmation_payload,
            status=status,
            steps=steps,
        )

    @staticmethod
    def _response(
        report: DeletionExecution,
    ) -> AdminApiResponse[DeletionExecution]:
        if report.status is DeletionExecutionStatus.COMPLETED:
            return AdminApiResponse.success(report)
        if report.status is DeletionExecutionStatus.PARTIAL:
            return AdminApiResponse(
                ok=False,
                data=report,
                error=AdminError(
                    AdminErrorCode.PARTIAL,
                    "删除已部分完成，可使用同一删除计划重试",
                ),
            )
        return AdminApiResponse(
            ok=False,
            data=report,
            error=AdminError(
                AdminErrorCode.INTERNAL,
                "删除存储步骤失败，未完成级联删除",
            ),
        )

    async def delete_uid(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionExecution]:
        """按单 UID 删除计划执行；确认串不匹配时不产生任何副作用。"""

        validated = _validate_plan(
            plan,
            confirmation_payload,
            scope="uid",
        )
        if not isinstance(validated, str):
            return validated
        database_result = await self._delete_uid_database(plan)
        steps = list(database_result.steps)
        steps.extend(
            (
                _preserved_step("user_privacy"),
                _preserved_step("personal_subscriptions"),
            )
        )
        steps.extend(_preserved_step(resource) for resource in _GROUP_PRESERVED_RESOURCES)
        status = (
            DeletionExecutionStatus.COMPLETED
            if database_result.committed
            else DeletionExecutionStatus.FAILED
        )
        report = self._report(plan, tuple(steps), status=status)
        return self._response(report)

    async def delete_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionExecution]:
        """按用户删除计划执行全部级联步骤，并返回逐项状态。"""

        validated = _validate_plan(
            plan,
            confirmation_payload,
            scope="user",
        )
        if not isinstance(validated, str):
            return validated
        database_result = await self._delete_user_database(plan)
        steps = list(database_result.steps)
        subscription_step = await self._delete_personal_subscriptions(
            user_id=validated,
            database_committed=database_result.committed,
        )
        steps.append(subscription_step)
        steps.extend(_preserved_step(resource) for resource in _GROUP_PRESERVED_RESOURCES)
        if not database_result.committed:
            status = DeletionExecutionStatus.FAILED
        elif subscription_step.status in (
            DeletionStepStatus.FAILED,
            DeletionStepStatus.SKIPPED,
        ):
            status = DeletionExecutionStatus.PARTIAL
        else:
            status = DeletionExecutionStatus.COMPLETED
        report = self._report(plan, tuple(steps), status=status)
        return self._response(report)

    async def execute_delete_uid(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionExecution]:
        """``delete_uid`` 的语义别名，便于 API adapter 表达执行动作。"""

        return await self.delete_uid(plan, confirmation_payload)

    async def execute_delete_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionExecution]:
        """``delete_user`` 的语义别名，便于 API adapter 表达执行动作。"""

        return await self.delete_user(plan, confirmation_payload)


UserDeletionCoordinator = AccountDeletionCoordinator
DeletionCoordinator = AccountDeletionCoordinator

__all__ = [
    "AccountDeletionCoordinator",
    "DeletionCoordinator",
    "UserDeletionCoordinator",
]
