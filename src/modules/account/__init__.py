"""账号与 UID 绑定 use case。"""

from .contracts import (
    AccountActor,
    AccountTransport,
    AccountTransportError,
    LoginAttempt,
    LoginChannel,
    LoginCredentials,
    LoginResult,
    RoleInfo,
    TransportErrorKind,
)
from .service import AccountService, parse_login_attempt

__all__ = [
    "AccountActor",
    "AccountService",
    "AccountTransport",
    "AccountTransportError",
    "LoginAttempt",
    "LoginChannel",
    "LoginCredentials",
    "LoginResult",
    "RoleInfo",
    "TransportErrorKind",
    "parse_login_attempt",
]
