"""AstrBot Dashboard Admin Web 适配器。

这一层是唯一接触 ``astrbot.api.web`` 的管理页入口：它读取已认证的
``PluginRequest``，把 JSON/form 参数转换为框架无关 DTO，调用 admin service，再将
统一的 ``AdminApiResponse`` 转成 HTTP JSON。业务规则、数据库和文件操作均留在
``src.modules.admin`` 或其下游 service 中。
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, cast
from urllib.parse import unquote

from astrbot.api.web import json_response, request

from ..modules.admin import (
    AdminAccount,
    AdminAccountUpdate,
    AdminApiResponse,
    AdminError,
    AdminErrorCode,
    AdminPreviewRequest,
    CredentialPayload,
    DeletionExecution,
    DeletionPreview,
    DeletionStepResult,
    GroupCleanupResult,
    MembershipCapability,
    MembershipProbeResult,
    MembershipScanResult,
    TaskTargetUpdate,
)
from ..version import get_plugin_version
from .event import EventActor
from .web import WebHandler, WebRoute

ADMIN_WEB_PREFIX = "/astrbot_plugin_dnaby/admin"

_ADMIN_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_HTTP_STATUS_BY_ERROR = {
    AdminErrorCode.VALIDATION: 400,
    AdminErrorCode.CONFLICT: 409,
    AdminErrorCode.UNSUPPORTED: 501,
    AdminErrorCode.NOT_FOUND: 404,
    AdminErrorCode.UPSTREAM: 502,
    AdminErrorCode.PARTIAL: 207,
    AdminErrorCode.INTERNAL: 500,
}
_SAFE_ERROR_MESSAGES = {
    AdminErrorCode.VALIDATION: "请求参数无效",
    AdminErrorCode.CONFLICT: "操作与当前状态冲突",
    AdminErrorCode.UNSUPPORTED: "当前平台不支持此操作",
    AdminErrorCode.NOT_FOUND: "资源不存在",
    AdminErrorCode.UPSTREAM: "上游服务暂时不可用，请稍后重试",
    AdminErrorCode.PARTIAL: "操作部分完成，请核对结果后重试",
    AdminErrorCode.INTERNAL: "管理服务内部错误，请稍后重试",
}


class _RequestValidation(ValueError):
    """请求解析失败；异常文本不会直接进入 HTTP 响应。"""


def _unauthorized_response() -> Any:
    return json_response(
        {
            "ok": False,
            "error": {
                "code": "unauthorized",
                "message": "需要 Dashboard 管理员认证",
            },
        },
        status_code=401,
        headers=dict(_ADMIN_HEADERS),
    )


def _internal_response() -> Any:
    return _response(
        AdminApiResponse.failure(
            AdminError(AdminErrorCode.INTERNAL, "管理服务内部错误，请稍后重试")
        )
    )


def _status_code(result: AdminApiResponse[Any]) -> int:
    if result.ok:
        return 200
    if result.error is None:
        return 500
    return _HTTP_STATUS_BY_ERROR.get(result.error.code, 500)


def _public_error_message(error: AdminError) -> str:
    return _SAFE_ERROR_MESSAGES[error.code]


def _serialize_value(value: object, *, include_credentials: bool = False) -> object:
    """只序列化已知 DTO，避免意外把 Path、异常或对象 repr 暴露给管理页。"""

    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, AdminAccount):
        return value.to_dict(include_credentials=include_credentials)
    if isinstance(value, DeletionPreview):
        return {
            "user_id": value.user_id,
            "uid": value.uid,
            "affected_uids": list(value.affected_uids),
            "delete_resources": list(value.delete_resources),
            "preserve_resources": list(value.preserve_resources),
            "confirmation_payload": value.confirmation_payload,
            "requires_confirmation": value.requires_confirmation,
        }
    if isinstance(value, MembershipCapability):
        return {
            "supported": value.supported,
            "platform": value.platform,
            "reason": value.reason,
        }
    if isinstance(value, MembershipProbeResult):
        return {
            "user_id": value.user_id,
            "group_id": value.group_id,
            "status": value.status.value,
            "platform": value.platform,
            "bot_id": value.bot_id,
            "reason": value.reason,
        }
    if isinstance(value, MembershipScanResult):
        return {
            "user_id": value.user_id,
            "groups": [
                _serialize_value(item, include_credentials=include_credentials)
                for item in value.groups
            ],
            "capability": _serialize_value(
                value.capability,
                include_credentials=include_credentials,
            ),
            "all_absent": value.all_absent,
            "has_present": value.has_present,
            "has_unknown": value.has_unknown,
            "has_unsupported": value.has_unsupported,
            "can_delete_user": value.can_delete_user,
        }
    if isinstance(value, GroupCleanupResult):
        return {
            "user_id": value.user_id,
            "group_id": value.group_id,
            "membership": _serialize_value(
                value.membership,
                include_credentials=include_credentials,
            ),
            "deleted_count": value.deleted_count,
        }
    if isinstance(value, DeletionStepResult):
        return {
            "resource": value.resource,
            "status": value.status.value,
            "count": value.count,
            "message": value.message,
        }
    if isinstance(value, DeletionExecution):
        return {
            "user_id": value.user_id,
            "uid": value.uid,
            "affected_uids": list(value.affected_uids),
            "confirmation_payload": value.confirmation_payload,
            "status": value.status.value,
            "steps": [
                _serialize_value(item, include_credentials=include_credentials)
                for item in value.steps
            ],
        }
    if isinstance(value, Mapping):
        return {
            str(key): _serialize_value(item, include_credentials=include_credentials)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _serialize_value(item, include_credentials=include_credentials)
            for item in value
        ]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if not isinstance(converted, Mapping):
            raise TypeError("管理 DTO to_dict 必须返回映射")
        return _serialize_value(
            converted,
            include_credentials=include_credentials,
        )
    raise TypeError("管理响应包含不可序列化对象")


def _response(
    result: object,
    *,
    include_credentials: bool = False,
) -> Any:
    """把 framework-free response 映射为固定 JSON envelope。"""

    if not isinstance(result, AdminApiResponse):
        result = AdminApiResponse.failure(
            AdminError(AdminErrorCode.INTERNAL, "管理服务返回结果无效")
        )
    typed_result = cast(AdminApiResponse[Any], result)
    try:
        body: dict[str, object] = {"ok": typed_result.ok}
        error = None
        if not typed_result.ok:
            error = typed_result.error or AdminError(
                AdminErrorCode.INTERNAL,
                "管理服务内部错误，请稍后重试",
            )
        if typed_result.ok or typed_result.data is not None:
            serialized_data = _serialize_value(
                typed_result.data,
                include_credentials=include_credentials,
            )
            if error is not None and error.code is AdminErrorCode.PARTIAL:
                if isinstance(serialized_data, Mapping):
                    serialized_data = dict(serialized_data)
                    serialized_data["operation_error"] = {
                        "code": error.code.value,
                        "message": _public_error_message(error),
                    }
            body["data"] = serialized_data
        if error is not None:
            body["error"] = {
                "code": error.code.value,
                "message": _public_error_message(error),
            }
        return json_response(
            body,
            status_code=_status_code(typed_result),
            headers=dict(_ADMIN_HEADERS),
        )
    except Exception:  # noqa: BLE001
        # DTO 序列化是安全边界；不把未知对象的 repr 或异常文本返回给浏览器。
        return json_response(
            {
                "ok": False,
                "error": {
                    "code": AdminErrorCode.INTERNAL.value,
                    "message": "管理服务内部错误，请稍后重试",
                },
            },
            status_code=500,
            headers=dict(_ADMIN_HEADERS),
        )


def _admin_handler(method: WebHandler) -> WebHandler:
    """给每个 Dashboard handler 加认证、解析错误和未知异常边界。"""

    @wraps(method)
    async def wrapped(
        self: AdminWebAdapter,
        *args: object,
        **kwargs: object,
    ) -> Any:
        try:
            username = request.username
            if not isinstance(username, str) or not username.strip():
                return _unauthorized_response()
            # AstrBot 的插件页桥接层会对动态路径段做 URL 编码；在统一 Web
            # 边界解码，确保中文角色名、用户标识等仍按服务层的规范值处理。
            decoded_args = tuple(
                unquote(value) if isinstance(value, str) else value for value in args
            )
            decoded_kwargs = {
                key: unquote(value) if isinstance(value, str) else value
                for key, value in kwargs.items()
            }
            return await method(self, *decoded_args, **decoded_kwargs)
        except _RequestValidation:
            return _response(
                AdminApiResponse.failure(
                    AdminError(AdminErrorCode.VALIDATION, "请求参数无效")
                )
            )
        except Exception:  # noqa: BLE001
            # handler 不能把本地路径、凭据或第三方异常 repr 传播到 HTTP 边界。
            return _internal_response()

    return cast(WebHandler, wrapped)


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _RequestValidation
    return value.strip()


def _query_string(key: str) -> str | None:
    value = request.query.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _RequestValidation
    return value


def _query_bool(key: str, *, default: bool) -> bool:
    value = _query_string(key)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise _RequestValidation


async def _json_object() -> Mapping[str, object]:
    payload = await request.json(default=None)
    if not isinstance(payload, Mapping):
        raise _RequestValidation
    return payload


def _credential_payload(value: object) -> CredentialPayload:
    if not isinstance(value, Mapping):
        raise _RequestValidation
    values: dict[str, str] = {}
    for key in (
        "app_cookie",
        "app_device_code",
        "app_d_num",
        "app_refresh_token",
        "app_status",
    ):
        field_value = value.get(key, "")
        if not isinstance(field_value, str):
            raise _RequestValidation
        values[key] = field_value
    return CredentialPayload(**values)


def _account_update(payload: Mapping[str, object]) -> AdminAccountUpdate:
    allowed = {"user_id", "uid", "group_id", "is_active", "credentials"}
    if any(key not in allowed for key in payload):
        raise _RequestValidation
    values: dict[str, object] = {
        key: payload[key]
        for key in ("user_id", "uid", "group_id", "is_active")
        if key in payload
    }
    if "credentials" in payload:
        values["credentials"] = _credential_payload(payload["credentials"])
    try:
        return AdminAccountUpdate(**cast(Any, values))
    except (TypeError, ValueError) as error:
        raise _RequestValidation from error


def _target_update(payload: Mapping[str, object]) -> TaskTargetUpdate:
    allowed = {
        "group_id",
        "bot_id",
        "user_type",
        "extra_message",
        "extra_data",
    }
    if any(key not in allowed for key in payload):
        raise _RequestValidation
    try:
        return TaskTargetUpdate(**{key: payload[key] for key in payload})
    except (TypeError, ValueError) as error:
        raise _RequestValidation from error


def _string_tuple(value: object, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _RequestValidation
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or (not allow_empty and not item.strip()):
            raise _RequestValidation
        result.append(item.strip())
    return tuple(result)


def _deletion_preview(payload: Mapping[str, object]) -> DeletionPreview:
    raw_plan = payload.get("plan", payload)
    if not isinstance(raw_plan, Mapping):
        raise _RequestValidation
    user_id = _required_string(raw_plan, "user_id")
    uid_value = raw_plan.get("uid")
    if uid_value is not None and (
        not isinstance(uid_value, str) or not uid_value.strip()
    ):
        raise _RequestValidation
    affected_uids = _string_tuple(
        raw_plan.get("affected_uids"),
        allow_empty=False,
    )
    delete_resources = _string_tuple(raw_plan.get("delete_resources", []))
    preserve_resources = _string_tuple(raw_plan.get("preserve_resources", []))
    plan_confirmation = _required_string(raw_plan, "confirmation_payload")
    requires_confirmation = raw_plan.get("requires_confirmation", True)
    if type(requires_confirmation) is not bool:
        raise _RequestValidation
    return DeletionPreview(
        user_id=user_id,
        uid=uid_value.strip() if isinstance(uid_value, str) else None,
        affected_uids=affected_uids,
        delete_resources=delete_resources,
        preserve_resources=preserve_resources,
        confirmation_payload=plan_confirmation,
        requires_confirmation=requires_confirmation,
    )


def _confirmation(payload: Mapping[str, object], *, expected: str | None = None) -> str:
    confirmed = payload.get("confirmed")
    if type(confirmed) is bool and confirmed:
        return expected or "confirmed"
    supplied = payload.get("confirmation_payload")
    if not isinstance(supplied, str) or not supplied.strip():
        raise _RequestValidation
    normalized = supplied.strip()
    if expected is not None and normalized != expected:
        raise _RequestValidation
    return normalized


class AdminWebAdapter:
    """将 admin service 集合适配为 Dashboard 可调用的认证 API。"""

    def __init__(self, services: Mapping[str, object]) -> None:
        self._services = dict(services)

    async def _call(
        self,
        service_key: str,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> AdminApiResponse[Any]:
        service = self._services.get(service_key)
        return await self._call_object(service, method_name, *args, **kwargs)

    @staticmethod
    async def _call_object(
        service: object | None,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> AdminApiResponse[Any]:
        method = getattr(service, method_name, None)
        if not callable(method):
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "管理服务不可用")
            )
        try:
            result = method(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception:  # noqa: BLE001
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "管理服务调用失败")
            )
        if not isinstance(result, AdminApiResponse):
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "管理服务返回结果无效")
            )
        return result

    def _deletion_coordinator(self) -> object | None:
        coordinator = self._services.get("deletion_coordinator")
        if coordinator is not None:
            return coordinator
        membership_service = self._services.get("membership_service")
        return getattr(membership_service, "deletion_coordinator", None)

    @_admin_handler
    async def bootstrap(self) -> Any:
        probe = await self._call("admin_api_service", "membership_capability")
        if not probe.ok:
            return _response(probe)
        if probe.data is None:
            return _internal_response()
        probe_data = _serialize_value(probe.data)
        return _response(
            AdminApiResponse.success(
                {
                    "version": get_plugin_version(),
                    "capabilities": {
                        "pages": True,
                        "admin_api": True,
                        "accounts": True,
                        "preview": True,
                        "tasks": True,
                        "targets": True,
                        "members": True,
                        "aliases": True,
                        "membership_probe": probe_data,
                    },
                }
            )
        )

    @_admin_handler
    async def list_accounts(self) -> Any:
        include_credentials = _query_bool("include_credentials", default=False)
        result = await self._call(
            "admin_account_service",
            "list_accounts",
            include_credentials=include_credentials,
        )
        return _response(result, include_credentials=include_credentials)

    @_admin_handler
    async def get_account(self, user_id: str, uid: str) -> Any:
        result = await self._call(
            "admin_account_service",
            "get_account",
            user_id,
            uid,
            include_credentials=True,
        )
        return _response(result, include_credentials=True)

    @_admin_handler
    async def update_account(self, user_id: str, uid: str) -> Any:
        result = await self._call(
            "admin_account_service",
            "update_account",
            user_id,
            uid,
            _account_update(await _json_object()),
        )
        return _response(result, include_credentials=True)

    @_admin_handler
    async def preview_delete_uid(self, user_id: str, uid: str) -> Any:
        result = await self._call(
            "admin_account_service",
            "preview_delete_uid",
            user_id,
            uid,
        )
        return _response(result)

    @_admin_handler
    async def preview_delete_user(self, user_id: str) -> Any:
        result = await self._call(
            "admin_account_service",
            "preview_delete_user",
            user_id,
        )
        return _response(result)

    async def _delete_uid(self, user_id: str, uid: str) -> Any:
        payload = await _json_object()
        plan = _deletion_preview(payload)
        if plan.user_id != user_id or plan.uid != uid:
            raise _RequestValidation
        confirmation = _required_string(payload, "confirmation_payload")
        result = await self._call_object(
            self._deletion_coordinator(),
            "delete_uid",
            plan,
            confirmation,
        )
        return _response(result)

    @_admin_handler
    async def delete_uid(self, user_id: str, uid: str) -> Any:
        return await self._delete_uid(user_id, uid)

    async def _delete_user(self, user_id: str) -> Any:
        payload = await _json_object()
        plan = _deletion_preview(payload)
        if plan.user_id != user_id or plan.uid is not None:
            raise _RequestValidation
        confirmation = _required_string(payload, "confirmation_payload")
        result = await self._call(
            "admin_api_service",
            "delete_member_user",
            plan,
            confirmation,
        )
        return _response(result)

    @_admin_handler
    async def delete_user(self, user_id: str) -> Any:
        return await self._delete_user(user_id)

    def _preview_request(
        self,
        user_id: str,
        uid: str,
        payload: Mapping[str, object],
    ) -> AdminPreviewRequest:
        char_name = payload.get("char_name")
        if char_name is not None and not isinstance(char_name, str):
            raise _RequestValidation
        weapon_names = _string_tuple(payload.get("weapon_names", []))
        username = cast(str, request.username).strip()
        try:
            actor = EventActor(user_id=username, bot_id="dashboard")
            return AdminPreviewRequest(
                actor=actor,
                user_id=user_id,
                uid=uid,
                char_name=char_name,
                weapon_names=weapon_names,
            )
        except (TypeError, ValueError) as error:
            raise _RequestValidation from error

    @_admin_handler
    async def preview_overview(self, user_id: str, uid: str) -> Any:
        preview_request = self._preview_request(
            user_id,
            uid,
            await _json_object(),
        )
        result = await self._call(
            "admin_preview_service",
            "preview_overview",
            preview_request,
        )
        return _response(result)

    @_admin_handler
    async def preview_detail(self, user_id: str, uid: str) -> Any:
        preview_request = self._preview_request(
            user_id,
            uid,
            await _json_object(),
        )
        result = await self._call(
            "admin_preview_service",
            "preview_detail",
            preview_request,
        )
        return _response(result)

    @_admin_handler
    async def list_tasks(self) -> Any:
        return _response(await self._call("admin_api_service", "list_tasks"))

    @_admin_handler
    async def get_task(self, task_id: str) -> Any:
        return _response(await self._call("admin_api_service", "get_task", task_id))

    @_admin_handler
    async def update_task(self, task_id: str) -> Any:
        payload = await _json_object()
        schedule = _required_string(payload, "schedule")
        result = await self._call(
            "admin_api_service",
            "update_task",
            task_id,
            schedule=schedule,
        )
        return _response(result)

    @_admin_handler
    async def pause_task(self, task_id: str) -> Any:
        return _response(await self._call("admin_api_service", "pause_task", task_id))

    @_admin_handler
    async def resume_task(self, task_id: str) -> Any:
        return _response(await self._call("admin_api_service", "resume_task", task_id))

    @_admin_handler
    async def delete_task(self, task_id: str) -> Any:
        payload = await _json_object()
        _confirmation(payload, expected=f"delete:task:{task_id}")
        return _response(await self._call("admin_api_service", "delete_task", task_id))

    @_admin_handler
    async def list_targets(self) -> Any:
        return _response(
            await self._call(
                "admin_api_service",
                "list_targets",
                _query_string("task_id"),
            )
        )

    @_admin_handler
    async def update_target(self, target_id: str) -> Any:
        return _response(
            await self._call(
                "admin_api_service",
                "update_target",
                target_id,
                _target_update(await _json_object()),
            )
        )

    @_admin_handler
    async def delete_target(self, target_id: str) -> Any:
        return _response(
            await self._call("admin_api_service", "delete_target", target_id)
        )

    @_admin_handler
    async def enable_target(self, target_id: str) -> Any:
        return _response(
            await self._call("admin_api_service", "enable_target", target_id)
        )

    @_admin_handler
    async def disable_target(self, target_id: str) -> Any:
        return _response(
            await self._call("admin_api_service", "disable_target", target_id)
        )

    @_admin_handler
    async def membership_capability(self) -> Any:
        return _response(await self._call("admin_api_service", "membership_capability"))

    @_admin_handler
    async def scan_members(self, user_id: str) -> Any:
        return _response(await self._call("admin_api_service", "scan_members", user_id))

    @_admin_handler
    async def cleanup_member_group(self, user_id: str, group_id: str) -> Any:
        return _response(
            await self._call(
                "admin_api_service",
                "cleanup_member_group",
                user_id,
                group_id,
            )
        )

    @_admin_handler
    async def delete_member_user(self, user_id: str) -> Any:
        payload = await _json_object()
        plan = _deletion_preview(payload)
        if plan.user_id != user_id or plan.uid is not None:
            raise _RequestValidation
        confirmation = _required_string(payload, "confirmation_payload")
        return _response(
            await self._call(
                "admin_api_service",
                "delete_member_user",
                plan,
                confirmation,
            )
        )

    @_admin_handler
    async def list_aliases(self) -> Any:
        return _response(await self._call("admin_alias_service", "list_aliases"))

    @_admin_handler
    async def add_alias(self, role_name: str) -> Any:
        payload = await _json_object()
        alias = _required_string(payload, "alias")
        return _response(
            await self._call(
                "admin_alias_service",
                "add_alias",
                role_name,
                alias,
            )
        )

    @_admin_handler
    async def delete_alias(self, role_name: str) -> Any:
        payload = await _json_object()
        alias = _required_string(payload, "alias")
        return _response(
            await self._call(
                "admin_alias_service",
                "delete_alias",
                role_name,
                alias,
            )
        )

    @_admin_handler
    async def restore_alias_role(self, role_name: str) -> Any:
        return _response(
            await self._call(
                "admin_alias_service",
                "restore_role",
                role_name,
            )
        )

    @_admin_handler
    async def restore_all_aliases(self) -> Any:
        return _response(await self._call("admin_alias_service", "restore_all"))

    def routes(self) -> tuple[WebRoute, ...]:
        """返回一次性注册到 Dashboard extension dispatcher 的全部路由。"""

        prefix = ADMIN_WEB_PREFIX
        return (
            WebRoute(f"{prefix}/bootstrap", self.bootstrap, ("GET",), "管理页初始化"),
            WebRoute(
                f"{prefix}/accounts/users/<user_id>/delete-preview",
                self.preview_delete_user,
                ("GET",),
                "预览用户删除",
            ),
            WebRoute(
                f"{prefix}/accounts/users/<user_id>/delete",
                self.delete_user,
                ("POST",),
                "执行用户删除",
            ),
            WebRoute(
                f"{prefix}/accounts", self.list_accounts, ("GET",), "全局账号列表"
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>",
                self.get_account,
                ("GET",),
                "读取账号详情",
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>",
                self.update_account,
                ("POST",),
                "更新账号详情",
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>/delete-preview",
                self.preview_delete_uid,
                ("GET",),
                "预览 UID 删除",
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>/delete",
                self.delete_uid,
                ("POST",),
                "执行 UID 删除",
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>/preview/overview",
                self.preview_overview,
                ("POST",),
                "预览玩家基本信息卡",
            ),
            WebRoute(
                f"{prefix}/accounts/<user_id>/<uid>/preview/detail",
                self.preview_detail,
                ("POST",),
                "预览玩家详情卡",
            ),
            WebRoute(f"{prefix}/tasks", self.list_tasks, ("GET",), "任务列表"),
            WebRoute(
                f"{prefix}/tasks/<task_id>",
                self.get_task,
                ("GET",),
                "读取任务",
            ),
            WebRoute(
                f"{prefix}/tasks/<task_id>",
                self.update_task,
                ("POST",),
                "更新任务调度",
            ),
            WebRoute(
                f"{prefix}/tasks/<task_id>/pause",
                self.pause_task,
                ("POST",),
                "暂停任务",
            ),
            WebRoute(
                f"{prefix}/tasks/<task_id>/resume",
                self.resume_task,
                ("POST",),
                "恢复任务",
            ),
            WebRoute(
                f"{prefix}/tasks/<task_id>/delete",
                self.delete_task,
                ("POST",),
                "永久删除任务",
            ),
            WebRoute(f"{prefix}/targets", self.list_targets, ("GET",), "投递目标列表"),
            WebRoute(
                f"{prefix}/targets/<target_id>",
                self.update_target,
                ("POST",),
                "更新投递目标",
            ),
            WebRoute(
                f"{prefix}/targets/<target_id>",
                self.delete_target,
                ("DELETE",),
                "删除投递目标",
            ),
            WebRoute(
                f"{prefix}/targets/<target_id>/delete",
                self.delete_target,
                ("POST",),
                "删除投递目标",
            ),
            WebRoute(
                f"{prefix}/targets/<target_id>/enable",
                self.enable_target,
                ("POST",),
                "启用公告投递目标",
            ),
            WebRoute(
                f"{prefix}/targets/<target_id>/disable",
                self.disable_target,
                ("POST",),
                "停用公告投递目标",
            ),
            WebRoute(
                f"{prefix}/members/capability",
                self.membership_capability,
                ("GET",),
                "成员探测能力",
            ),
            WebRoute(
                f"{prefix}/members/<user_id>/scan",
                self.scan_members,
                ("POST",),
                "扫描用户关联群",
            ),
            WebRoute(
                f"{prefix}/members/<user_id>/groups/<group_id>/cleanup",
                self.cleanup_member_group,
                ("POST",),
                "清理单群个人订阅",
            ),
            WebRoute(
                f"{prefix}/members/<user_id>/delete",
                self.delete_member_user,
                ("POST",),
                "执行全局用户清理",
            ),
            WebRoute(f"{prefix}/aliases", self.list_aliases, ("GET",), "角色别名列表"),
            WebRoute(
                f"{prefix}/aliases/restore-all",
                self.restore_all_aliases,
                ("POST",),
                "恢复全部默认别名",
            ),
            WebRoute(
                f"{prefix}/aliases/<role_name>",
                self.add_alias,
                ("POST",),
                "添加角色自定义别名",
            ),
            WebRoute(
                f"{prefix}/aliases/<role_name>",
                self.delete_alias,
                ("DELETE",),
                "删除角色自定义别名",
            ),
            WebRoute(
                f"{prefix}/aliases/<role_name>/delete",
                self.delete_alias,
                ("POST",),
                "删除角色自定义别名",
            ),
            WebRoute(
                f"{prefix}/aliases/<role_name>/restore",
                self.restore_alias_role,
                ("POST",),
                "恢复角色默认别名",
            ),
        )


def build_admin_web_routes(services: Mapping[str, object]) -> tuple[WebRoute, ...]:
    """按已解析 service 构造管理页路由，供 bootstrap 注入 ``WebRegistrar``。"""

    return AdminWebAdapter(services).routes()


__all__ = ["ADMIN_WEB_PREFIX", "AdminWebAdapter", "build_admin_web_routes"]
