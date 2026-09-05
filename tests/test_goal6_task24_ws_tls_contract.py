"""Goal 6 T24：legacy 官方业务 WebSocket 的 TLS 证书校验契约。"""

from __future__ import annotations

import ssl
import threading
from typing import Any

import pytest

from src.utils.api import ws_manager as ws_manager_module


class _FakeWebSocketApp:
    """只记录 websocket-client 实际收到的 run_forever 参数。"""

    instances: list[_FakeWebSocketApp] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.run_options: dict[str, Any] | None = None
        self.run_started = threading.Event()
        self.closed = False
        self.__class__.instances.append(self)

    def run_forever(self, **options: Any) -> None:
        self.run_options = options
        self.run_started.set()

    def close(self) -> None:
        self.closed = True


def _build_ws_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ws_manager_module.WebSocketManager, _FakeWebSocketApp]:
    manager = ws_manager_module.WebSocketManager()
    _FakeWebSocketApp.instances = []
    monkeypatch.setattr(ws_manager_module.websocket, "WebSocketApp", _FakeWebSocketApp)
    monkeypatch.setattr(manager, "_start_heartbeat", lambda *_args: None)

    connection = manager.get_connection("token", "device")
    assert connection is not None
    fake = _FakeWebSocketApp.instances[0]
    assert fake.run_started.wait(2)
    return manager, fake


def test_legacy_websocket_requires_server_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """官方业务 WS 不得关闭服务器证书校验或主机名校验。"""

    manager, fake = _build_ws_probe(monkeypatch)
    try:
        assert fake.run_options is not None
        ssl_options = fake.run_options.get("sslopt", {})
        assert ssl_options.get("cert_reqs", ssl.CERT_REQUIRED) == ssl.CERT_REQUIRED
        assert ssl_options.get("check_hostname", True) is True
    finally:
        manager.close_all()
