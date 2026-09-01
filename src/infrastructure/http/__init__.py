"""账号和外部 API transport 适配层。

仅在访问具体 transport 符号时延迟导入，避免 `entry.response` 仅需要临时文件
工具时触发 account -> response 的循环依赖。
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DEFAULT_CODE_URL",
    "AccountTransportError",
    "DnaApiAccountTransport",
    "DnaApiCheckinTransport",
    "DnaApiEncyclopediaTransport",
    "DnaApiNoticesTransport",
    "DnaApiPlayerTransport",
    "RequestConcurrencyGate",
    "TransportErrorKind",
]

_SYMBOL_MODULES = {
    "AccountTransportError": ".account",
    "DnaApiAccountTransport": ".account",
    "TransportErrorKind": ".account",
    "DnaApiCheckinTransport": ".checkin",
    "RequestConcurrencyGate": ".concurrency",
    "DEFAULT_CODE_URL": ".encyclopedia",
    "DnaApiEncyclopediaTransport": ".encyclopedia",
    "DnaApiNoticesTransport": ".notices",
    "DnaApiPlayerTransport": ".player",
}


def __getattr__(name: str):
    module_name = _SYMBOL_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
