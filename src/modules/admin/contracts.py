"""账号管理 service 的 typed DTO。

这些类型不依赖 AstrBot Web handler。凭据字段在管理详情 DTO 中保持明文，
但默认 ``repr``、字符串化和响应 envelope 的诊断表示都只显示状态/存在性。
调用方只有显式调用 ``to_plaintext_dict`` 时才会取得完整字段映射。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Generic, TypeVar

CREDENTIAL_FIELDS = (
    "app_cookie",
    "app_device_code",
    "app_d_num",
    "app_refresh_token",
    "app_status",
)

ADMIN_NO_STORE_HEADERS = MappingProxyType({"Cache-Control": "no-store"})


class AdminErrorCode(StrEnum):
    """管理 API 统一错误分类。"""

    VALIDATION = "validation"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"
    UPSTREAM = "upstream"
    PARTIAL = "partial"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class AdminError:
    """不携带异常原文或凭据的可展示错误。"""

    code: AdminErrorCode
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", AdminErrorCode(self.code))


ResponseData = TypeVar("ResponseData")


@dataclass(frozen=True, slots=True)
class AdminApiResponse(Generic[ResponseData]):
    """框架无关的统一响应 envelope。

    管理响应统一附带 ``Cache-Control: no-store``，使后续 Web adapter 不会因漏配
    某个凭据读写路由而把明文留在浏览器或中间缓存中。
    """

    ok: bool
    data: ResponseData | None = None
    error: AdminError | None = None
    headers: dict[str, str] = field(
        default_factory=lambda: dict(ADMIN_NO_STORE_HEADERS),
    )

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("成功响应不得携带 error")
        if not self.ok and self.error is None:
            raise ValueError("失败响应必须携带 error")

    @classmethod
    def success(cls, data: ResponseData) -> AdminApiResponse[ResponseData]:
        """建立成功响应。"""

        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: AdminError) -> AdminApiResponse[ResponseData]:
        """建立失败响应。"""

        return cls(ok=False, error=error)

    @property
    def cache_control(self) -> str:
        """返回后续 HTTP adapter 应发送的缓存策略。"""

        return self.headers["Cache-Control"]


@dataclass(frozen=True, slots=True)
class CredentialPayload:
    """管理详情可编辑的完整 App 凭据。

    这些字段故意使用普通字符串，以便管理页在认证边界内展示原值；默认表示仍
    只输出 App 状态与字段存在性，避免日志调用 ``repr(payload)`` 时泄露 secret。
    """

    app_cookie: str = field(default="", repr=False)
    app_device_code: str = field(default="", repr=False)
    app_d_num: str = field(default="", repr=False)
    app_refresh_token: str = field(default="", repr=False)
    app_status: str = ""

    def __post_init__(self) -> None:
        for field_name in CREDENTIAL_FIELDS:
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} 必须是字符串")

    @property
    def has_app_credentials(self) -> bool:
        """返回 App 是否至少保存了一个非空凭据字段。"""

        return any(
            (
                self.app_cookie,
                self.app_device_code,
                self.app_d_num,
                self.app_refresh_token,
            )
        )

    def to_plaintext_dict(self) -> dict[str, str]:
        """显式导出完整明文，供已认证管理写入/响应边界使用。"""

        return {
            field_name: getattr(self, field_name) for field_name in CREDENTIAL_FIELDS
        }

    def as_plaintext_dict(self) -> dict[str, str]:
        """``to_plaintext_dict`` 的语义别名，便于 Web adapter 序列化。"""

        return self.to_plaintext_dict()

    def __repr__(self) -> str:
        """只输出状态和存在性，不输出任何凭据值。"""

        return (
            "CredentialPayload("
            f"app_status={self.app_status!r}, "
            f"has_app_credentials={self.has_app_credentials!r})"
        )


@dataclass(frozen=True, slots=True)
class AdminAccount:
    """全局用户/UID 绑定及其凭据状态。"""

    user_id: str
    uid: str
    group_id: str | None
    is_active: bool
    has_app_credentials: bool
    app_status: str = ""
    credentials: CredentialPayload | None = field(default=None, repr=False)

    def to_dict(self, *, include_credentials: bool = False) -> dict[str, object]:
        """导出管理 API 视图；明文必须由调用方显式选择。"""

        payload: dict[str, str] | None = None
        if include_credentials and self.credentials is not None:
            payload = self.credentials.to_plaintext_dict()
        return {
            "user_id": self.user_id,
            "uid": self.uid,
            "group_id": self.group_id,
            "is_active": self.is_active,
            "has_app_credentials": self.has_app_credentials,
            "app_status": self.app_status,
            "credentials": payload,
        }

    def __repr__(self) -> str:
        """账号列表/日志表示不携带明文凭据。"""

        return (
            "AdminAccount("
            f"user_id={self.user_id!r}, uid={self.uid!r}, "
            f"group_id={self.group_id!r}, is_active={self.is_active!r}, "
            f"has_app_credentials={self.has_app_credentials!r}, "
            f"app_status={self.app_status!r})"
        )


class _Unset:
    """区分 patch 未提供字段与显式清空 group_id。"""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class AdminAccountUpdate:
    """已有账号的可编辑字段。

    ``user_id``/``uid`` 只是前端回显的只读身份键；service 会校验它们必须与路径
    身份一致。它们不存在迁移/重命名语义，因此不会创建或移动账号。
    """

    user_id: str | None = None
    uid: str | None = None
    group_id: str | None | _Unset = UNSET
    is_active: bool | _Unset = UNSET
    credentials: CredentialPayload | _Unset = field(default=UNSET, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("user_id", "uid"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} 不能为空")
        if (
            self.group_id is not UNSET
            and self.group_id is not None
            and not isinstance(self.group_id, str)
        ):
            raise TypeError("group_id 必须是字符串或 None")
        if self.is_active is not UNSET and not isinstance(self.is_active, bool):
            raise TypeError("is_active 必须是 bool")
        if self.credentials is not UNSET and not isinstance(
            self.credentials,
            CredentialPayload,
        ):
            raise TypeError("credentials 必须是 CredentialPayload")

    def __repr__(self) -> str:
        """patch 的诊断表示仅显示是否携带凭据，不显示凭据内容。"""

        return (
            "AdminAccountUpdate("
            f"user_id={self.user_id!r}, uid={self.uid!r}, "
            f"group_id={self.group_id!r}, is_active={self.is_active!r}, "
            f"has_credentials={self.credentials is not UNSET!r})"
        )


@dataclass(frozen=True, slots=True)
class DeletionPreview:
    """删除动作的只读影响范围，实际删除留给后续级联 service。"""

    user_id: str
    uid: str | None
    affected_uids: tuple[str, ...]
    delete_resources: tuple[str, ...]
    preserve_resources: tuple[str, ...]
    confirmation_payload: str
    requires_confirmation: bool = True

    @property
    def will_delete(self) -> tuple[str, ...]:
        """与设计文档措辞一致的删除资源别名。"""

        return self.delete_resources

    @property
    def will_preserve(self) -> tuple[str, ...]:
        """与设计文档措辞一致的保留资源别名。"""

        return self.preserve_resources


class DeletionStepStatus(StrEnum):
    """级联删除中单个资源的可观测状态。"""

    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"
    PRESERVED = "preserved"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class DeletionStepResult:
    """不携带异常原文的单个级联步骤结果。"""

    resource: str
    status: DeletionStepStatus
    count: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeletionStepStatus(self.status))
        if self.count < 0:
            raise ValueError("删除步骤数量不能为负数")


class DeletionExecutionStatus(StrEnum):
    """一次删除协调的总状态。"""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeletionExecution:
    """可重试的级联删除结果及逐资源状态。"""

    user_id: str
    uid: str | None
    affected_uids: tuple[str, ...]
    confirmation_payload: str
    status: DeletionExecutionStatus
    steps: tuple[DeletionStepResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeletionExecutionStatus(self.status))

    @property
    def items(self) -> tuple[DeletionStepResult, ...]:
        """``steps`` 的 API 友好别名。"""

        return self.steps

    def step(self, resource: str) -> DeletionStepResult:
        """按资源名取得步骤；未知资源显式报错。"""

        for step in self.steps:
            if step.resource == resource:
                return step
        raise KeyError(resource)

    def __repr__(self) -> str:
        """诊断表示仅保留删除范围，不展开任何存储异常原文。"""

        return (
            "DeletionExecution("
            f"user_id={self.user_id!r}, uid={self.uid!r}, "
            f"affected_uids={self.affected_uids!r}, "
            f"confirmation_payload={self.confirmation_payload!r}, "
            f"status={self.status.value!r}, steps={self.steps!r})"
        )


__all__ = [
    "ADMIN_NO_STORE_HEADERS",
    "CREDENTIAL_FIELDS",
    "UNSET",
    "AdminAccount",
    "AdminAccountUpdate",
    "AdminApiResponse",
    "AdminError",
    "AdminErrorCode",
    "CredentialPayload",
    "DeletionExecution",
    "DeletionExecutionStatus",
    "DeletionPreview",
    "DeletionStepResult",
    "DeletionStepStatus",
]
