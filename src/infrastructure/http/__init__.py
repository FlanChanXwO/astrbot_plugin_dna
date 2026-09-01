"""账号和外部 API transport 适配层。"""

from .account import (
    AccountTransportError,
    DnaApiAccountTransport,
    TransportErrorKind,
)
from .checkin import DnaApiCheckinTransport
from .concurrency import RequestConcurrencyGate
from .encyclopedia import DEFAULT_CODE_URL, DnaApiEncyclopediaTransport
from .notices import DnaApiNoticesTransport
from .player import DnaApiPlayerTransport

__all__ = [
    "DEFAULT_CODE_URL",
    "AccountTransportError",
    "DnaApiAccountTransport",
    "DnaApiCheckinTransport",
    "RequestConcurrencyGate",
    "DnaApiEncyclopediaTransport",
    "DnaApiNoticesTransport",
    "DnaApiPlayerTransport",
    "TransportErrorKind",
]
