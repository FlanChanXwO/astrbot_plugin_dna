"""账号领域的 typed request、结果、凭据值对象和 transport 协议。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from ...entry.event import EventActor

AccountActor = EventActor


class LoginChannel(StrEnum):
    """登录凭据所属渠道；rewrite 只接受官方 App 凭据。"""

    APP = "app"


class TransportErrorKind(StrEnum):
    """可向用户区分的 transport 失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    SERVER = "server"


class AccountTransportError(Exception):
    """transport 失败的安全载体。

    detail 只供内部诊断使用；异常字符串固定为类别摘要，避免调用方把
    服务端原文、URL 查询参数或凭据带进日志和用户响应。
    """

    def __init__(
        self,
        kind: TransportErrorKind,
        *,
        detail: str = "",
        status_code: int | None = None,
    ) -> None:
        self.kind = kind
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"account transport {kind.value} failure")

    def __repr__(self) -> str:
        """不把 detail 或 status code 拼入 repr，避免异常被意外序列化。"""

        return f"AccountTransportError(kind={self.kind.value!r})"


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    """已经完成格式校验的登录输入。"""

    mode: Literal["token", "sms"]
    token: str = field(default="", repr=False)
    mobile: str = field(default="", repr=False)
    code: str = field(default="", repr=False)
    channel: LoginChannel = LoginChannel.APP
    dev_code: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        """在进入 transport 前固定输入形态并拒绝歧义值。"""

        channel = LoginChannel(self.channel)
        object.__setattr__(self, "channel", channel)
        if self.mode == "token":
            token = self.token.strip()
            if not token:
                raise ValueError("token 不能为空")
            object.__setattr__(self, "token", token)
            object.__setattr__(self, "dev_code", self.dev_code.strip())
            return
        if self.mode == "sms":
            mobile = self.mobile.strip()
            code = self.code.strip()
            if re.fullmatch(r"1[3-9]\d{9}", mobile) is None:
                raise ValueError("手机号格式错误")
            if re.fullmatch(r"\d{4}", code) is None:
                raise ValueError("验证码格式错误")
            object.__setattr__(self, "mobile", mobile)
            object.__setattr__(self, "code", code)
            object.__setattr__(self, "dev_code", self.dev_code.strip())
            return
        raise ValueError(f"不支持的登录模式: {self.mode!r}")

    @classmethod
    def from_token(
        cls,
        token: str,
        *,
        channel: LoginChannel = LoginChannel.APP,
        dev_code: str = "",
    ) -> LoginAttempt:
        """建立 token 登录请求。"""

        return cls(
            mode="token",
            token=token,
            channel=channel,
            dev_code=dev_code,
        )

    @classmethod
    def from_sms(
        cls,
        mobile: str,
        code: str,
        *,
        channel: LoginChannel = LoginChannel.APP,
        dev_code: str = "",
    ) -> LoginAttempt:
        """建立手机号验证码登录请求。"""

        return cls(
            mode="sms",
            mobile=mobile,
            code=code,
            channel=channel,
            dev_code=dev_code,
        )

    def __repr__(self) -> str:
        """只显示输入类型和字段存在性。"""

        return (
            "LoginAttempt("
            f"mode={self.mode!r}, channel={self.channel.value!r}, "
            f"has_token={bool(self.token)!r}, has_mobile={bool(self.mobile)!r}, "
            f"has_code={bool(self.code)!r})"
        )


@dataclass(frozen=True, slots=True)
class LoginCredentials:
    """登录成功后由 transport 返回的凭据。

    App token、refresh token、设备码和 d_num 都不出现在 repr 中。
    """

    channel: LoginChannel
    token: str = field(repr=False)
    dev_code: str = field(repr=False)
    d_num: str = field(default="", repr=False)
    refresh_token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        """拒绝空凭据，确保成功结果能被持久化。"""

        object.__setattr__(self, "channel", LoginChannel(self.channel))
        token = self.token.strip()
        dev_code = self.dev_code.strip()
        if not token:
            raise ValueError("token 不能为空")
        if not dev_code:
            raise ValueError("devCode 不能为空")
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "dev_code", dev_code)

    def __repr__(self) -> str:
        """仅返回非敏感诊断信息。"""

        return (
            "LoginCredentials("
            f"channel={self.channel.value!r}, has_token={bool(self.token)!r}, "
            f"has_device_code={bool(self.dev_code)!r}, "
            f"has_d_num={bool(self.d_num)!r}, "
            f"has_refresh_token={bool(self.refresh_token)!r})"
        )


@dataclass(frozen=True, slots=True)
class RoleInfo:
    """登录 transport 返回的角色摘要。"""

    uid: str
    name: str | None = None
    is_default: bool = False

    def __post_init__(self) -> None:
        """保证角色标识不会以空白值进入 normalized binding。"""

        uid = self.uid.strip()
        if not uid:
            raise ValueError("角色 UID 不能为空")
        object.__setattr__(self, "uid", uid)
        if self.name is not None:
            name = self.name.strip()
            object.__setattr__(self, "name", name or None)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """transport 的终态结果，不包含网络响应原文。"""

    status: Literal["success", "cancelled", "failed"]
    credentials: LoginCredentials | None = field(default=None, repr=False)
    roles: tuple[RoleInfo, ...] = ()

    def __post_init__(self) -> None:
        """约束终态与凭据的组合，避免伪造成功。"""

        if self.status not in {"success", "cancelled", "failed"}:
            raise ValueError(f"不支持的登录结果: {self.status!r}")
        if self.status == "success" and self.credentials is None:
            raise ValueError("登录成功结果缺少凭据")
        if self.status != "success" and self.credentials is not None:
            raise ValueError("非成功结果不得携带凭据")
        object.__setattr__(self, "roles", tuple(self.roles))

    @classmethod
    def success(
        cls,
        credentials: LoginCredentials,
        *,
        roles: tuple[RoleInfo, ...] = (),
    ) -> LoginResult:
        """建立成功结果。"""

        return cls(status="success", credentials=credentials, roles=roles)

    @classmethod
    def cancelled(cls) -> LoginResult:
        """建立用户取消结果；忽略 transport 展示文案。"""

        return cls(status="cancelled")

    @classmethod
    def failed(cls) -> LoginResult:
        """建立已知失败结果；不携带服务端原文。"""

        return cls(status="failed")

    def __repr__(self) -> str:
        """只显示终态和角色数量，不显示潜在服务端文案。"""

        return (
            "LoginResult("
            f"status={self.status!r}, roles={len(self.roles)!r}, "
            f"has_credentials={self.credentials is not None!r})"
        )


class AccountTransport(Protocol):
    """账号服务需要的最小、可替换 App transport 协议。"""

    async def begin_login(self, actor: AccountActor) -> str:
        """创建登录页会话并返回可展示地址。"""
        ...

    async def authenticate(self, attempt: LoginAttempt) -> LoginResult:
        """使用已经校验的 token 或短信输入完成认证。"""
        ...

    async def authenticate_credentials(
        self,
        credentials: LoginCredentials,
    ) -> LoginResult:
        """校验外部登录服务返回的 App 凭据并补齐角色列表。"""
        ...

    async def request_sms_code(
        self,
        mobile: str,
        validation: str,
        dev_code: str,
    ) -> None:
        """为内置登录页请求 App 短信验证码。"""
        ...


__all__ = [
    "AccountActor",
    "AccountTransport",
    "AccountTransportError",
    "LoginAttempt",
    "LoginChannel",
    "LoginCredentials",
    "LoginResult",
    "RoleInfo",
    "TransportErrorKind",
]
