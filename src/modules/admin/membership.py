"""成员探测、跨群复核和用户级清理的框架无关 use case。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from inspect import isawaitable
from typing import Any, Protocol

from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.subscriptions import SubscriptionStore
from ..notices import messages as notices_messages
from .contracts import (
    AdminApiResponse,
    AdminError,
    AdminErrorCode,
    DeletionExecution,
    DeletionPreview,
)
from .deletion import AccountDeletionCoordinator


class MembershipStatus(StrEnum):
    """成员关系的唯一三态结果。"""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MembershipCapability:
    """当前运行环境是否可以可靠执行成员探测。"""

    supported: bool
    platform: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MembershipProbeResult:
    """单个用户在单个群的三态探测结果。"""

    user_id: str
    group_id: str
    status: MembershipStatus
    platform: str | None = None
    bot_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", MembershipStatus(self.status))


@dataclass(frozen=True, slots=True)
class MembershipScanResult:
    """一个用户的全部关联群扫描快照。"""

    user_id: str
    results: tuple[MembershipProbeResult, ...]
    capability: MembershipCapability

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))

    @property
    def groups(self) -> tuple[MembershipProbeResult, ...]:
        """``results`` 的语义别名，方便 API adapter 表达群列表。"""

        return self.results

    @property
    def all_absent(self) -> bool:
        """只有每个关联群都被明确判定为 absent 才返回 True。"""

        return all(item.status is MembershipStatus.ABSENT for item in self.results)

    @property
    def has_present(self) -> bool:
        """是否仍有群明确包含该用户。"""

        return any(item.status is MembershipStatus.PRESENT for item in self.results)

    @property
    def has_unknown(self) -> bool:
        """是否存在无法可靠判断的关联群。"""

        return any(item.status is MembershipStatus.UNKNOWN for item in self.results)

    @property
    def has_unsupported(self) -> bool:
        """是否有群因平台能力不可用而无法核验。"""

        return not self.capability.supported or any(
            item.reason == "unsupported" for item in self.results
        )

    @property
    def can_delete_user(self) -> bool:
        """返回全局删除安全门禁是否通过。"""

        return self.all_absent and not self.has_unsupported and not self.has_unknown


@dataclass(frozen=True, slots=True)
class GroupCleanupResult:
    """单群清理的可观察结果。"""

    user_id: str
    group_id: str
    membership: MembershipProbeResult
    deleted_count: int = 0

    @property
    def status(self) -> MembershipStatus:
        """返回清理前的成员状态。"""

        return self.membership.status

    @property
    def subscriptions_deleted(self) -> int:
        """``deleted_count`` 的 API 语义别名。"""

        return self.deleted_count


class MembershipProbe(Protocol):
    """可注入的成员探测器协议。"""

    def capability(self) -> MembershipCapability:
        """返回平台能力，而不是把不可用伪装成 absent。"""

        ...

    async def check(
        self,
        group_id: str,
        user_id: str,
        *,
        bot_id: str | None = None,
    ) -> MembershipProbeResult:
        """探测一个用户是否仍在指定群中。"""

        ...


def _failure(
    code: AdminErrorCode,
    message: str,
    *,
    data: Any = None,
) -> AdminApiResponse[Any]:
    """建立不泄露上游异常的管理失败响应。"""

    return AdminApiResponse(
        ok=False,
        data=data,
        error=AdminError(code, message),
    )


def _normalized_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _coerce_capability(value: object) -> MembershipCapability:
    if isinstance(value, MembershipCapability):
        return value
    supported = bool(getattr(value, "supported", False))
    platform = getattr(value, "platform", None)
    reason = getattr(value, "reason", None)
    return MembershipCapability(
        supported=supported,
        platform=str(platform) if platform is not None else None,
        reason=str(reason) if reason is not None else None,
    )


def _coerce_result(
    value: object,
    *,
    user_id: str,
    group_id: str,
    capability: MembershipCapability,
) -> MembershipProbeResult:
    if isinstance(value, MembershipProbeResult):
        if value.user_id != user_id or value.group_id != group_id:
            return MembershipProbeResult(
                user_id=user_id,
                group_id=group_id,
                status=MembershipStatus.UNKNOWN,
                platform=capability.platform,
                reason="invalid_result",
            )
        return value
    if isinstance(value, MembershipStatus | str):
        try:
            status = MembershipStatus(value)
        except ValueError:
            status = MembershipStatus.UNKNOWN
        return MembershipProbeResult(
            user_id=user_id,
            group_id=group_id,
            status=status,
            platform=capability.platform,
            reason=None if status is not MembershipStatus.UNKNOWN else "invalid_result",
        )
    if isinstance(value, Mapping):
        raw_status = value.get("status")
        try:
            status = MembershipStatus(raw_status)
        except (TypeError, ValueError):
            status = MembershipStatus.UNKNOWN
        return MembershipProbeResult(
            user_id=user_id,
            group_id=group_id,
            status=status,
            platform=capability.platform,
            reason=(
                str(value.get("reason"))
                if value.get("reason") is not None
                else (
                    None if status is not MembershipStatus.UNKNOWN else "invalid_result"
                )
            ),
        )
    return MembershipProbeResult(
        user_id=user_id,
        group_id=group_id,
        status=MembershipStatus.UNKNOWN,
        platform=capability.platform,
        reason="invalid_result",
    )


class MembershipService:
    """执行成员扫描、群级清理和删除前的全局二次复核。"""

    def __init__(
        self,
        database: AsyncDatabase,
        subscriptions: SubscriptionStore | None,
        probe: MembershipProbe,
        deletion_coordinator: object | None = None,
    ) -> None:
        self.database = database
        self.subscriptions = subscriptions
        self.probe = probe
        self.deletion_coordinator = deletion_coordinator or AccountDeletionCoordinator(
            database,
            subscriptions,
        )

    def capability(self) -> MembershipCapability:
        """返回当前 probe 能力；生产能力仅接受 aiocqhttp。"""

        try:
            raw_capability = self.probe.capability
            value = raw_capability() if callable(raw_capability) else raw_capability
            capability = _coerce_capability(value)
        except Exception:  # noqa: BLE001
            return MembershipCapability(
                supported=False,
                reason="capability_unavailable",
            )
        if capability.supported and capability.platform != "aiocqhttp":
            return MembershipCapability(
                supported=False,
                platform=capability.platform,
                reason="unsupported_platform",
            )
        return capability

    def get_capability(self) -> MembershipCapability:
        """``capability`` 的显式 getter。"""

        return self.capability()

    def capability_response(self) -> AdminApiResponse[MembershipCapability]:
        """返回供 bootstrap/API adapter 使用的能力响应。"""

        capability = self.capability()
        if not capability.supported:
            return AdminApiResponse(
                ok=False,
                data=capability,
                error=AdminError(
                    AdminErrorCode.UNSUPPORTED,
                    "当前平台不支持群成员探测",
                ),
            )
        return AdminApiResponse.success(capability)

    async def _associated_groups(self, user_id: str) -> tuple[str, ...]:
        groups: dict[str, None] = {}
        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list(
                session,
                user_id=user_id,
            )
        for binding in bindings:
            group_id = _normalized_id(binding.group_id)
            if group_id is not None:
                groups.setdefault(group_id, None)

        if self.subscriptions is not None:
            personal_subscriptions = await self.subscriptions.get(
                notices_messages.MH_SUBSCRIBE,
                user_id=user_id,
            )
            for subscription in personal_subscriptions:
                group_id = _normalized_id(subscription.group_id)
                if (
                    group_id is not None
                    and subscription.uid == user_id
                    and subscription.user_type == "group"
                ):
                    groups.setdefault(group_id, None)
        return tuple(groups)

    async def _probe_one(
        self,
        group_id: str,
        user_id: str,
        capability: MembershipCapability,
    ) -> MembershipProbeResult:
        if not capability.supported:
            return MembershipProbeResult(
                user_id=user_id,
                group_id=group_id,
                status=MembershipStatus.UNKNOWN,
                platform=capability.platform,
                reason="unsupported",
            )
        check = getattr(self.probe, "check", None)
        if not callable(check):
            return MembershipProbeResult(
                user_id=user_id,
                group_id=group_id,
                status=MembershipStatus.UNKNOWN,
                platform=capability.platform,
                reason="probe_unavailable",
            )
        try:
            value = check(group_id, user_id)
            if isawaitable(value):
                value = await value
        except Exception:  # noqa: BLE001
            return MembershipProbeResult(
                user_id=user_id,
                group_id=group_id,
                status=MembershipStatus.UNKNOWN,
                platform=capability.platform,
                reason="upstream_error",
            )
        return _coerce_result(
            value,
            user_id=user_id,
            group_id=group_id,
            capability=capability,
        )

    async def scan_user(self, user_id: str) -> AdminApiResponse[MembershipScanResult]:
        """扫描一个用户的全部关联群。"""

        normalized_user_id = _normalized_id(user_id)
        if normalized_user_id is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 不能为空")
        try:
            groups = await self._associated_groups(normalized_user_id)
        except Exception:  # noqa: BLE001
            return _failure(
                AdminErrorCode.UPSTREAM,
                "无法读取用户关联群，请稍后重试",
            )

        capability = self.capability()
        results = tuple(
            [
                await self._probe_one(group_id, normalized_user_id, capability)
                for group_id in groups
            ]
        )
        scan = MembershipScanResult(
            user_id=normalized_user_id,
            results=results,
            capability=capability,
        )
        if not capability.supported:
            return _failure(
                AdminErrorCode.UNSUPPORTED,
                "当前平台不支持群成员探测",
                data=scan,
            )
        return AdminApiResponse.success(scan)

    async def scan(self, user_id: str) -> AdminApiResponse[MembershipScanResult]:
        """``scan_user`` 的简短别名。"""

        return await self.scan_user(user_id)

    async def cleanup_group(
        self,
        user_id: str,
        group_id: str,
    ) -> AdminApiResponse[GroupCleanupResult]:
        """确认用户 absent 后，只删除该群可归属的个人密函订阅。"""

        normalized_user_id = _normalized_id(user_id)
        normalized_group_id = _normalized_id(group_id)
        if normalized_user_id is None or normalized_group_id is None:
            return _failure(AdminErrorCode.VALIDATION, "user_id 和 group_id 不能为空")

        capability = self.capability()
        membership = await self._probe_one(
            normalized_group_id,
            normalized_user_id,
            capability,
        )
        empty_result = GroupCleanupResult(
            user_id=normalized_user_id,
            group_id=normalized_group_id,
            membership=membership,
        )
        if not capability.supported:
            return _failure(
                AdminErrorCode.UNSUPPORTED,
                "当前平台不支持群成员探测",
                data=empty_result,
            )
        if membership.status is MembershipStatus.PRESENT:
            return _failure(
                AdminErrorCode.CONFLICT,
                "用户仍在该群中，未执行群清理",
                data=empty_result,
            )
        if membership.status is MembershipStatus.UNKNOWN:
            return _failure(
                AdminErrorCode.UPSTREAM,
                "无法确认用户群成员状态，未执行群清理",
                data=empty_result,
            )
        if self.subscriptions is None:
            return _failure(
                AdminErrorCode.INTERNAL,
                "订阅存储不可用，未执行群清理",
                data=empty_result,
            )
        try:
            deleted_count = (
                await self.subscriptions.delete_personal_subscriptions_for_group(
                    normalized_user_id,
                    normalized_group_id,
                    subscription_type=notices_messages.MH_SUBSCRIBE,
                )
            )
        except Exception:  # noqa: BLE001
            return _failure(
                AdminErrorCode.INTERNAL,
                "群订阅清理失败，可重试",
                data=empty_result,
            )
        return AdminApiResponse.success(
            GroupCleanupResult(
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                membership=membership,
                deleted_count=deleted_count,
            )
        )

    async def clean_group(
        self,
        user_id: str,
        group_id: str,
    ) -> AdminApiResponse[GroupCleanupResult]:
        """``cleanup_group`` 的动作命名别名。"""

        return await self.cleanup_group(user_id, group_id)

    @staticmethod
    def _validate_delete_request(
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> str | AdminApiResponse[Any]:
        if not isinstance(plan, DeletionPreview):
            return _failure(AdminErrorCode.VALIDATION, "删除计划类型错误")
        user_id = _normalized_id(plan.user_id)
        if user_id is None or user_id != plan.user_id:
            return _failure(AdminErrorCode.VALIDATION, "删除计划 user_id 无效")
        if plan.uid is not None or not plan.affected_uids:
            return _failure(AdminErrorCode.VALIDATION, "全局删除计划范围不一致")
        if any(
            not _normalized_id(uid) or uid != uid.strip() for uid in plan.affected_uids
        ):
            return _failure(AdminErrorCode.VALIDATION, "删除计划包含无效 UID")
        if len(set(plan.affected_uids)) != len(plan.affected_uids):
            return _failure(AdminErrorCode.VALIDATION, "删除计划包含重复 UID")
        expected = f"delete:user:{user_id}"
        if plan.confirmation_payload != expected or confirmation_payload != expected:
            return _failure(AdminErrorCode.VALIDATION, "删除确认串与目标身份不匹配")
        return user_id

    async def delete_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
        *,
        scan: MembershipScanResult | None = None,
    ) -> AdminApiResponse[DeletionExecution]:
        """删除前忽略旧 scan，重新核验所有关联群后才调用删除协调器。"""

        del scan
        validated = self._validate_delete_request(plan, confirmation_payload)
        if not isinstance(validated, str):
            return validated

        scan_response = await self.scan_user(validated)
        scan_result = scan_response.data
        if scan_result is None:
            if scan_response.error is not None:
                return _failure(scan_response.error.code, scan_response.error.message)
            return _failure(
                AdminErrorCode.UPSTREAM,
                "无法确认用户群成员状态，未执行全局删除",
            )
        if scan_result.has_unsupported:
            return _failure(
                AdminErrorCode.UNSUPPORTED,
                "存在无法核验的关联群，未执行全局删除",
                data=scan_result,
            )
        if scan_result.has_present:
            return _failure(
                AdminErrorCode.CONFLICT,
                "用户仍在关联群中，未执行全局删除",
                data=scan_result,
            )
        if not scan_result.can_delete_user:
            return _failure(
                AdminErrorCode.UPSTREAM,
                "存在无法确认的关联群，未执行全局删除",
                data=scan_result,
            )

        delete_user = getattr(self.deletion_coordinator, "delete_user", None)
        if not callable(delete_user):
            return _failure(
                AdminErrorCode.INTERNAL,
                "删除协调器不可用，未执行全局删除",
            )
        try:
            result = delete_user(plan, confirmation_payload)
            if isawaitable(result):
                result = await result
        except Exception:  # noqa: BLE001
            return _failure(
                AdminErrorCode.INTERNAL,
                "全局删除协调失败，可重试",
            )
        if not isinstance(result, AdminApiResponse):
            return _failure(
                AdminErrorCode.INTERNAL,
                "删除协调器返回结果无效",
            )
        return result

    async def execute_delete_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
        *,
        scan: MembershipScanResult | None = None,
    ) -> AdminApiResponse[DeletionExecution]:
        """``delete_user`` 的 API adapter 语义别名。"""

        return await self.delete_user(
            plan,
            confirmation_payload,
            scan=scan,
        )

    async def delete_global_user(
        self,
        plan: DeletionPreview,
        confirmation_payload: str,
    ) -> AdminApiResponse[DeletionExecution]:
        """全局删除动作的显式命名别名。"""

        return await self.delete_user(plan, confirmation_payload)


class AiocqhttpMembershipProbe:
    """只使用 aiocqhttp/OneBot V11 raw client 的生产 probe。"""

    def __init__(
        self,
        raw_client: object | None = None,
        *,
        context: object | None = None,
        platform: object | None = None,
        platform_id: str | None = None,
        platform_name: str | None = None,
        platform_resolver: Callable[[str | None], object | None] | None = None,
    ) -> None:
        self.raw_client = raw_client
        self.context = context
        self.platform = platform
        self.platform_id = platform_id
        self.platform_name = platform_name
        self.platform_resolver = platform_resolver

    @staticmethod
    def _platform_name(platform: object | None) -> str | None:
        if platform is None:
            return None
        try:
            metadata = getattr(platform, "meta", None)
            metadata = metadata() if callable(metadata) else metadata
            name = getattr(metadata, "name", None)
            if name is not None:
                return str(name)
        except Exception:  # noqa: BLE001
            return None
        config = getattr(platform, "config", None)
        if isinstance(config, Mapping) and config.get("type") is not None:
            return str(config["type"])
        return None

    def _resolve_platform(self) -> object | None:
        if self.platform is not None:
            return self.platform
        if self.platform_resolver is not None:
            try:
                return self.platform_resolver(self.platform_id)
            except Exception:  # noqa: BLE001
                return None
        if self.context is None:
            return None

        if self.platform_id is not None:
            get_platform_inst = getattr(self.context, "get_platform_inst", None)
            if callable(get_platform_inst):
                try:
                    platform = get_platform_inst(self.platform_id)
                except Exception:  # noqa: BLE001
                    platform = None
                if platform is not None:
                    return platform

        manager = getattr(self.context, "platform_manager", None)
        get_insts = getattr(manager, "get_insts", None)
        if callable(get_insts):
            try:
                raw_platforms = get_insts()
                platforms = (
                    tuple(raw_platforms) if isinstance(raw_platforms, Iterable) else ()
                )
            except Exception:  # noqa: BLE001
                platforms = ()
        else:
            raw_platforms = getattr(manager, "platform_insts", ())
            platforms = (
                tuple(raw_platforms) if isinstance(raw_platforms, Iterable) else ()
            )
        if self.platform_id is not None:
            for platform in platforms:
                metadata = getattr(platform, "meta", None)
                metadata = metadata() if callable(metadata) else metadata
                if getattr(metadata, "id", None) == self.platform_id:
                    return platform
        return next(
            (
                platform
                for platform in platforms
                if self._platform_name(platform) == "aiocqhttp"
            ),
            None,
        )

    @staticmethod
    def _has_member_action(client: object) -> bool:
        return callable(getattr(client, "get_group_member_list", None)) or callable(
            getattr(client, "call_action", None)
        )

    def _resolve_raw_client(self, platform: object | None) -> object | None:
        if self.raw_client is not None:
            return self.raw_client
        if self._platform_name(platform) != "aiocqhttp":
            return None
        get_client = getattr(platform, "get_client", None)
        if callable(get_client):
            try:
                client = get_client()
            except Exception:  # noqa: BLE001
                client = None
            if client is not None:
                return client
        return getattr(platform, "bot", None)

    def capability(self) -> MembershipCapability:
        """不支持/缺少 raw action 时显式报告 disabled。"""

        platform = self._resolve_platform()
        detected_platform_name = self._platform_name(platform)
        platform_name = detected_platform_name or self.platform_name
        if self.raw_client is not None and platform_name is None:
            platform_name = "aiocqhttp"
        if platform_name != "aiocqhttp":
            return MembershipCapability(
                supported=False,
                platform=platform_name,
                reason="unsupported_platform",
            )
        client = self._resolve_raw_client(platform)
        if client is None or not self._has_member_action(client):
            return MembershipCapability(
                supported=False,
                platform=platform_name,
                reason="client_unavailable",
            )
        return MembershipCapability(supported=True, platform="aiocqhttp")

    @staticmethod
    def _api_group_id(group_id: str) -> int | str:
        return int(group_id) if group_id.isdigit() else group_id

    @staticmethod
    def _member_ids(response: object) -> tuple[str, ...] | None:
        if isinstance(response, Mapping):
            status = response.get("status")
            if status is not None and status not in ("ok", True):
                return None
            response = response.get("data")
        if not isinstance(response, (list, tuple)):
            return None
        member_ids: list[str] = []
        for member in response:
            if not isinstance(member, Mapping):
                return None
            raw_user_id = member.get("user_id")
            if raw_user_id is None or not str(raw_user_id).strip():
                return None
            member_ids.append(str(raw_user_id).strip())
        return tuple(member_ids)

    async def check(
        self,
        group_id: str,
        user_id: str,
        *,
        bot_id: str | None = None,
    ) -> MembershipProbeResult:
        """调用 OneBot `get_group_member_list(group_id=...)` 并严格解析响应。"""

        capability = self.capability()
        base = {
            "user_id": user_id,
            "group_id": group_id,
            "platform": capability.platform,
            "bot_id": bot_id,
        }
        if not capability.supported:
            return MembershipProbeResult(
                **base,
                status=MembershipStatus.UNKNOWN,
                reason="unsupported",
            )
        client = self._resolve_raw_client(self._resolve_platform())
        if client is None:
            return MembershipProbeResult(
                **base,
                status=MembershipStatus.UNKNOWN,
                reason="client_unavailable",
            )
        try:
            method = getattr(client, "get_group_member_list", None)
            if callable(method):
                response = method(group_id=self._api_group_id(group_id))
            else:
                call_action = getattr(client, "call_action", None)
                if not callable(call_action):
                    return MembershipProbeResult(
                        **base,
                        status=MembershipStatus.UNKNOWN,
                        reason="client_unavailable",
                    )
                response = call_action(
                    "get_group_member_list",
                    group_id=self._api_group_id(group_id),
                )
            if isawaitable(response):
                response = await response
        except Exception:  # noqa: BLE001
            return MembershipProbeResult(
                **base,
                status=MembershipStatus.UNKNOWN,
                reason="upstream_error",
            )

        member_ids = self._member_ids(response)
        if member_ids is None:
            return MembershipProbeResult(
                **base,
                status=MembershipStatus.UNKNOWN,
                reason="incomplete_response",
            )
        status = (
            MembershipStatus.PRESENT
            if str(user_id).strip() in member_ids
            else MembershipStatus.ABSENT
        )
        return MembershipProbeResult(**base, status=status)


MembershipProbeCapability = MembershipCapability
MembershipProbeStatus = MembershipStatus
AccountMembershipService = MembershipService
MembershipCleanupService = MembershipService


__all__ = [
    "AccountMembershipService",
    "AiocqhttpMembershipProbe",
    "GroupCleanupResult",
    "MembershipCapability",
    "MembershipCleanupService",
    "MembershipProbe",
    "MembershipProbeCapability",
    "MembershipProbeResult",
    "MembershipProbeStatus",
    "MembershipScanResult",
    "MembershipService",
    "MembershipStatus",
]
