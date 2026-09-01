"""任务、投递目标和成员管理的框架无关 API service。

本模块只编排已有 registry、scheduler、订阅存储和成员 service，不注册 WebRoute，
也不提供任务/目标创建能力。Task 12 的 Web adapter 只需完成请求解析、认证和响应
序列化即可复用这里的统一错误契约。
"""

from __future__ import annotations

import base64
import binascii
import inspect
import json
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from ...infrastructure.scheduler_state import (
    BUILTIN_SCHEDULER_TASK_IDS,
    SchedulerRegistry,
    SchedulerTaskDeleted,
    SchedulerTaskNotDeletable,
    SchedulerTaskNotFound,
    SchedulerTaskNotPausable,
    SchedulerTaskSnapshot,
    SchedulerTaskUnavailable,
    normalize_scheduler_schedule,
)
from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from ..checkin import messages as checkin_messages
from ..notices import messages as notices_messages
from ..notices.target_service import (
    AnnouncementTargetService,
    TargetMutationResult,
    TargetMutationStatus,
)
from .contracts import UNSET, AdminApiResponse, AdminError, AdminErrorCode

TaskSnapshot = SchedulerTaskSnapshot

_TASK_IDS = frozenset(BUILTIN_SCHEDULER_TASK_IDS)
_TASK_TARGET_TYPES: dict[str, frozenset[str]] = {
    "dnaby_sign_daily": frozenset((checkin_messages.SIGN_RESULT_SUBSCRIBE,)),
    "dnaby_sign_cleanup": frozenset(),
    "dnaby_mh_push": frozenset(
        (
            notices_messages.MH_SUBSCRIBE,
            notices_messages.MH_PIC_SUBSCRIBE,
            notices_messages.MH_TEXT_SUBSCRIBE,
        )
    ),
    "dnaby_ann_poll": frozenset((notices_messages.ANN_SUBSCRIBE,)),
}
_CONFIG_FIELDS: dict[str, tuple[str, str]] = {
    "dnaby_sign_daily": ("sign_in", "sign_time"),
    "dnaby_ann_poll": ("notifications", "announcement_check_minutes"),
}
_MISSING = object()


def _failure(
    code: AdminErrorCode,
    message: str,
    *,
    data: Any = None,
) -> AdminApiResponse[Any]:
    """建立不暴露异常原文的失败 envelope。"""

    return AdminApiResponse(
        ok=False,
        data=data,
        error=AdminError(code, message),
    )


def _target_id(sub_type: str, origin: str, uid: str) -> str:
    payload = json.dumps(
        [sub_type, origin, uid],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_target_id(value: object) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("target_id 无效")
    try:
        encoded = value.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (
        UnicodeEncodeError,
        UnicodeDecodeError,
        ValueError,
        binascii.Error,
    ) as error:
        raise ValueError("target_id 无效") from error
    if (
        not isinstance(payload, list)
        or len(payload) != 3
        or any(not isinstance(item, str) for item in payload)
        or not payload[0]
        or not payload[1]
    ):
        raise ValueError("target_id 无效")
    decoded = (payload[0], payload[1], payload[2])
    if _target_id(*decoded) != value:
        raise ValueError("target_id 无效")
    return decoded


@dataclass(frozen=True, slots=True)
class TaskTarget:
    """可供管理页展示的现有订阅目标。"""

    id: str
    subscription_type: str
    unified_msg_origin: str
    user_id: str
    group_id: str
    bot_id: str
    user_type: str
    uid: str
    extra_message: str
    extra_data: str
    enabled: bool = True
    provenance: str = "legacy"
    managed: bool = False

    @classmethod
    def from_subscription(cls, subscription: Subscription) -> TaskTarget:
        """将订阅值对象转换为稳定 ID 的管理 DTO。"""

        return cls(
            id=_target_id(
                subscription.type,
                subscription.unified_msg_origin,
                subscription.uid,
            ),
            subscription_type=subscription.type,
            unified_msg_origin=subscription.unified_msg_origin,
            user_id=subscription.user_id,
            group_id=subscription.group_id,
            bot_id=subscription.bot_id,
            user_type=subscription.user_type,
            uid=subscription.uid,
            extra_message=subscription.extra_message,
            extra_data=subscription.extra_data,
            enabled=subscription.enabled,
            provenance=subscription.provenance,
            managed=subscription.provenance == "chat_command",
        )

    @property
    def target_id(self) -> str:
        """``id`` 的语义别名，便于 Web adapter 命名。"""

        return self.id

    @property
    def type(self) -> str:
        """订阅类型别名，保持与 ``Subscription`` 的字段名一致。"""

        return self.subscription_type

    def to_dict(self) -> dict[str, object]:
        """导出 JSON 兼容目标视图。"""

        return {
            "id": self.id,
            "type": self.subscription_type,
            "unified_msg_origin": self.unified_msg_origin,
            "user_id": self.user_id,
            "group_id": self.group_id,
            "bot_id": self.bot_id,
            "user_type": self.user_type,
            "uid": self.uid,
            "extra_message": self.extra_message,
            "extra_data": self.extra_data,
            "enabled": self.enabled,
            "provenance": self.provenance,
            "managed": self.managed,
        }


@dataclass(frozen=True, slots=True)
class TaskTargetUpdate:
    """已有目标的可编辑字段；身份键由 target ID 固定，不允许移动。"""

    group_id: str | None | object = UNSET
    bot_id: str | None | object = UNSET
    user_type: str | None | object = UNSET
    extra_message: str | None | object = UNSET
    extra_data: str | None | object = UNSET

    def __post_init__(self) -> None:
        for field_name in (
            "group_id",
            "bot_id",
            "user_type",
            "extra_message",
            "extra_data",
        ):
            value = getattr(self, field_name)
            if value is not UNSET and value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} 必须是字符串、None 或 UNSET")


def _patch_value(value: object, previous: str) -> str:
    if value is UNSET:
        return previous
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise TypeError("目标更新字段必须是字符串或 None")


class AdminApiService:
    """提供任务/目标/成员管理动作，不提供创建或恢复入口。"""

    def __init__(
        self,
        registry: SchedulerRegistry,
        subscriptions: SubscriptionStore,
        schedulers: Mapping[str, object] | None = None,
        membership_service: object | None = None,
        *,
        task_schedulers: Mapping[str, object] | None = None,
        config_store: MutableMapping[str, Any] | None = None,
        save_config: Callable[[], object] | None = None,
        announcement_target_service: AnnouncementTargetService | None = None,
    ) -> None:
        if schedulers is not None and task_schedulers is not None:
            raise ValueError("schedulers 与 task_schedulers 只能提供一个")
        self.registry = registry
        self.subscriptions = subscriptions
        self.schedulers = dict(task_schedulers or schedulers or {})
        self.membership_service = membership_service
        self.announcement_target_service = announcement_target_service
        self.config_store = config_store
        self._save_config = save_config

    @staticmethod
    def _is_known_task(task_id: object) -> bool:
        return isinstance(task_id, str) and task_id in _TASK_IDS

    async def list_tasks(self) -> AdminApiResponse[tuple[TaskSnapshot, ...]]:
        """只返回四个内置任务，过滤 registry 中可能存在的扩展定义。"""

        try:
            snapshots = await self.registry.list_snapshots()
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "任务列表读取失败")
        return AdminApiResponse.success(
            tuple(snapshot for snapshot in snapshots if snapshot.id in _TASK_IDS)
        )

    async def get_task(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        if not self._is_known_task(task_id):
            return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
        try:
            snapshot = await self.registry.get_snapshot(task_id)
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "任务读取失败")
        if snapshot is None:
            return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
        return AdminApiResponse.success(snapshot)

    @staticmethod
    def _scheduler_failure(error: Exception) -> AdminApiResponse[Any]:
        if isinstance(error, SchedulerTaskNotFound):
            return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
        if isinstance(
            error,
            (
                SchedulerTaskDeleted,
                SchedulerTaskNotDeletable,
                SchedulerTaskNotPausable,
                SchedulerTaskUnavailable,
            ),
        ):
            return _failure(AdminErrorCode.CONFLICT, "任务当前状态不允许该操作")
        if isinstance(error, ValueError):
            return _failure(AdminErrorCode.VALIDATION, "任务参数无效")
        return _failure(AdminErrorCode.INTERNAL, "任务操作失败，可重试")

    async def _task_action(
        self,
        task_id: str,
        action_name: str,
    ) -> AdminApiResponse[TaskSnapshot]:
        if not self._is_known_task(task_id):
            return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
        try:
            if await self.registry.is_deleted(task_id):
                return _failure(AdminErrorCode.CONFLICT, "任务已永久删除且不可恢复")
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "任务读取失败")
        current = await self.get_task(task_id)
        if not current.ok or current.data is None:
            return current
        scheduler = self.schedulers.get(task_id)
        action = getattr(scheduler, action_name, None)
        if not callable(action):
            return _failure(AdminErrorCode.INTERNAL, "任务控制器不可用")
        try:
            result = action(task_id)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001
            return self._scheduler_failure(error)
        if action_name == "delete_task":
            # 删除后 registry 会隐藏 tombstone，响应保留删除前快照供确认页收口。
            return AdminApiResponse.success(current.data)
        updated = await self.get_task(task_id)
        if not updated.ok or updated.data is None:
            return updated
        return updated

    async def update_task(
        self,
        task_id: str,
        *,
        schedule: str,
    ) -> AdminApiResponse[TaskSnapshot]:
        """更新已有任务的 schedule；成功后运行中的 loop 立即重排。"""

        if not self._is_known_task(task_id):
            return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
        if task_id == "dnaby_mh_push":
            return _failure(AdminErrorCode.CONFLICT, "密函任务时间固定为每小时 HH:30")
        try:
            normalized = normalize_scheduler_schedule(task_id, schedule)
        except Exception as error:  # noqa: BLE001
            return self._scheduler_failure(error)

        current = await self.get_task(task_id)
        if not current.ok or current.data is None:
            return current
        scheduler = self.schedulers.get(task_id)
        action = getattr(scheduler, "update_task", None)
        if not callable(action):
            return _failure(AdminErrorCode.INTERNAL, "任务控制器不可用")
        previous_schedule = current.data.schedule
        try:
            result = action(task_id, normalized)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001
            return self._scheduler_failure(error)

        try:
            await self._persist_schedule(task_id, normalized)
        except Exception:  # noqa: BLE001
            try:
                rollback = action(task_id, previous_schedule)
                if inspect.isawaitable(rollback):
                    await rollback
            except Exception:  # noqa: BLE001
                return _failure(
                    AdminErrorCode.PARTIAL,
                    "任务已更新但配置保存失败，当前状态需要重试核对",
                )
            return _failure(AdminErrorCode.INTERNAL, "任务配置保存失败，未保留更新")

        updated = await self.get_task(task_id)
        if not updated.ok or updated.data is None:
            return updated
        return updated

    async def _persist_schedule(self, task_id: str, schedule: str) -> None:
        if self.config_store is None or task_id not in _CONFIG_FIELDS:
            return
        if not isinstance(self.config_store, MutableMapping):
            raise TypeError("配置存储不可写")
        section_name, field_name = _CONFIG_FIELDS[task_id]
        section = self.config_store.get(section_name)
        if section is None:
            section = {}
            self.config_store[section_name] = section
        if not isinstance(section, MutableMapping):
            raise TypeError("配置分组不可写")
        if task_id == "dnaby_sign_daily":
            value: object = schedule.split("@", 1)[1]
        else:
            value = int(schedule.removeprefix("interval@").removesuffix("m"))
        previous = section.get(field_name, _MISSING)
        section[field_name] = value
        try:
            if self._save_config is not None:
                saved = self._save_config()
                if inspect.isawaitable(saved):
                    await saved
            else:
                save_config = getattr(self.config_store, "save_config", None)
                if callable(save_config):
                    saved = save_config()
                    if inspect.isawaitable(saved):
                        await saved
        except BaseException:
            if previous is _MISSING:
                del section[field_name]
            else:
                section[field_name] = previous
            raise

    async def pause_task(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self._task_action(task_id, "pause_task")

    async def resume_task(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self._task_action(task_id, "resume_task")

    async def delete_task(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self._task_action(task_id, "delete_task")

    async def pause(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self.pause_task(task_id)

    async def resume(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self.resume_task(task_id)

    async def delete(self, task_id: str) -> AdminApiResponse[TaskSnapshot]:
        return await self.delete_task(task_id)

    async def list_targets(
        self,
        task_id: str | None = None,
    ) -> AdminApiResponse[tuple[TaskTarget, ...]]:
        """列出全部或指定内置任务可投递的现有订阅目标。"""

        target_types: frozenset[str] | None = None
        if task_id is not None:
            if not self._is_known_task(task_id):
                return _failure(AdminErrorCode.NOT_FOUND, "任务不存在")
            task = await self.get_task(task_id)
            if not task.ok:
                return _failure(
                    task.error.code
                    if task.error is not None
                    else AdminErrorCode.INTERNAL,
                    task.error.message if task.error is not None else "任务不存在",
                )
            target_types = _TASK_TARGET_TYPES[task_id]
        try:
            subscriptions = await self.subscriptions.list_all()
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标读取失败")
        return AdminApiResponse.success(
            tuple(
                TaskTarget.from_subscription(subscription)
                for subscription in subscriptions
                if target_types is None or subscription.type in target_types
            )
        )

    async def _find_target(
        self,
        key: tuple[str, str, str],
    ) -> Subscription | None:
        sub_type, origin, uid = key
        return next(
            (
                subscription
                for subscription in await self.subscriptions.list_all()
                if (
                    subscription.type == sub_type
                    and subscription.unified_msg_origin == origin
                    and subscription.uid == uid
                )
            ),
            None,
        )

    async def _announcement_target_action(
        self,
        action: str,
        target_id: str,
    ) -> AdminApiResponse[TaskTarget]:
        service = self.announcement_target_service
        if service is None:
            return _failure(AdminErrorCode.INTERNAL, "公告目标服务不可用")
        try:
            key = _decode_target_id(target_id)
        except ValueError:
            return _failure(AdminErrorCode.VALIDATION, "target_id 无效")
        if key[0] != notices_messages.ANN_SUBSCRIBE:
            return _failure(AdminErrorCode.UNSUPPORTED, "该目标类型不支持公告生命周期操作")
        try:
            existing = await self._find_target(key)
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标读取失败")
        if existing is None:
            return _failure(AdminErrorCode.NOT_FOUND, "公告目标不存在")
        if existing.provenance != "chat_command":
            return _failure(AdminErrorCode.UNSUPPORTED, "该公告目标来源未核验，不能由管理页操作")
        method = getattr(service, action, None)
        if not callable(method):
            return _failure(AdminErrorCode.INTERNAL, "公告目标服务不可用")
        try:
            result = method(target_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.UPSTREAM, "公告目标操作失败，可重试")
        if not isinstance(result, TargetMutationResult):
            return _failure(AdminErrorCode.INTERNAL, "公告目标服务返回结果无效")
        if result.status is TargetMutationStatus.INVALID:
            return _failure(AdminErrorCode.VALIDATION, result.message or "target_id 无效")
        if result.status is TargetMutationStatus.NOT_FOUND:
            return _failure(AdminErrorCode.NOT_FOUND, result.message or "公告目标不存在")
        if result.subscription is None:
            return _failure(AdminErrorCode.INTERNAL, "公告目标服务未返回目标")
        target = TaskTarget.from_subscription(result.subscription)
        if result.status is TargetMutationStatus.PARTIAL:
            return _failure(AdminErrorCode.PARTIAL, result.message or "公告目标操作部分完成", data=target)
        return AdminApiResponse.success(target)

    async def update_target(
        self,
        target_id: str,
        update: TaskTargetUpdate,
    ) -> AdminApiResponse[TaskTarget]:
        if not isinstance(update, TaskTargetUpdate):
            return _failure(AdminErrorCode.VALIDATION, "目标更新请求类型错误")
        try:
            key = _decode_target_id(target_id)
            target = await self._find_target(key)
        except ValueError:
            return _failure(AdminErrorCode.VALIDATION, "target_id 无效")
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标读取失败")
        if target is None:
            return _failure(AdminErrorCode.NOT_FOUND, "投递目标不存在")
        if target.type == notices_messages.ANN_SUBSCRIBE:
            return _failure(AdminErrorCode.UNSUPPORTED, "公告目标只能通过生命周期操作管理，身份不可移动")
        replacement = Subscription(
            type=target.type,
            unified_msg_origin=target.unified_msg_origin,
            user_id=target.user_id,
            group_id=_patch_value(update.group_id, target.group_id),
            bot_id=_patch_value(update.bot_id, target.bot_id),
            user_type=_patch_value(update.user_type, target.user_type),
            uid=target.uid,
            extra_message=_patch_value(update.extra_message, target.extra_message),
            extra_data=_patch_value(update.extra_data, target.extra_data),
            enabled=target.enabled,
            provenance=target.provenance,
        )
        try:
            replaced = await self.subscriptions.replace_target(*key, replacement)
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标保存失败，可重试")
        if replaced is None:
            return _failure(AdminErrorCode.NOT_FOUND, "投递目标不存在")
        return AdminApiResponse.success(TaskTarget.from_subscription(replaced))

    async def delete_target(self, target_id: str) -> AdminApiResponse[TaskTarget]:
        try:
            key = _decode_target_id(target_id)
            target = await self._find_target(key)
        except ValueError:
            return _failure(AdminErrorCode.VALIDATION, "target_id 无效")
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标读取失败")
        if target is None:
            return _failure(AdminErrorCode.NOT_FOUND, "投递目标不存在")
        if target.type == notices_messages.ANN_SUBSCRIBE:
            return await self._announcement_target_action("delete", target_id)
        try:
            deleted = await self.subscriptions.delete(*key)
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.INTERNAL, "投递目标删除失败，可重试")
        if not deleted:
            return _failure(AdminErrorCode.NOT_FOUND, "投递目标不存在")
        return AdminApiResponse.success(TaskTarget.from_subscription(target))

    async def disable_target(self, target_id: str) -> AdminApiResponse[TaskTarget]:
        return await self._announcement_target_action("disable", target_id)

    async def enable_target(self, target_id: str) -> AdminApiResponse[TaskTarget]:
        return await self._announcement_target_action("enable", target_id)

    async def _membership_action(
        self,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> AdminApiResponse[Any]:
        if self.membership_service is None:
            return _failure(AdminErrorCode.INTERNAL, "成员服务不可用")
        method = getattr(self.membership_service, method_name, None)
        if not callable(method):
            return _failure(AdminErrorCode.INTERNAL, "成员服务不可用")
        try:
            result = method(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception:  # noqa: BLE001
            return _failure(AdminErrorCode.UPSTREAM, "成员服务请求失败，可重试")
        if not isinstance(result, AdminApiResponse):
            return _failure(AdminErrorCode.INTERNAL, "成员服务返回结果无效")
        return result

    async def membership_capability(self) -> AdminApiResponse[Any]:
        return await self._membership_action("capability_response")

    async def scan_members(self, user_id: str) -> AdminApiResponse[Any]:
        return await self._membership_action("scan_user", user_id)

    async def cleanup_member_group(
        self,
        user_id: str,
        group_id: str,
    ) -> AdminApiResponse[Any]:
        return await self._membership_action("cleanup_group", user_id, group_id)

    async def delete_member_user(
        self,
        plan: object,
        confirmation_payload: str,
        *,
        scan: object | None = None,
    ) -> AdminApiResponse[Any]:
        return await self._membership_action(
            "delete_user",
            plan,
            confirmation_payload,
            scan=scan,
        )

    async def scan(self, user_id: str) -> AdminApiResponse[Any]:
        return await self.scan_members(user_id)

    async def cleanup_group(
        self,
        user_id: str,
        group_id: str,
    ) -> AdminApiResponse[Any]:
        return await self.cleanup_member_group(user_id, group_id)

    async def delete_user(
        self,
        plan: object,
        confirmation_payload: str,
        *,
        scan: object | None = None,
    ) -> AdminApiResponse[Any]:
        return await self.delete_member_user(
            plan,
            confirmation_payload,
            scan=scan,
        )


AdminTaskService = AdminApiService
TaskAdminService = AdminApiService

__all__ = [
    "AdminApiService",
    "AdminTaskService",
    "TaskAdminService",
    "TaskSnapshot",
    "TaskTarget",
    "TaskTargetUpdate",
]
