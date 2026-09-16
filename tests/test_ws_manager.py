"""官方业务 WebSocket 首请求握手回归测试。"""

from __future__ import annotations

import base64
import json

from src.utils.api import ws_manager as ws_module


def test_wait_ready_sends_initial_user_ping_before_return(monkeypatch) -> None:
    """wait_ready 返回前必须已发送携带 userId 的首个业务心跳。"""

    sent: list[str] = []

    class _Sock:
        connected = True

    class _WebSocketApp:
        def __init__(
            self,
            _url: str,
            *,
            header: list[str],
            on_open,
            on_message,
            on_error,
            on_close,
        ) -> None:
            del header, on_message, on_error, on_close
            self.sock = _Sock()
            self._on_open = on_open

        def send(self, payload: str) -> None:
            sent.append(payload)

        def run_forever(self, **_kwargs) -> None:
            self._on_open(self)

        def close(self) -> None:
            self.sock.connected = False

    monkeypatch.setattr(ws_module.websocket, "WebSocketApp", _WebSocketApp)
    payload = base64.urlsafe_b64encode(
        json.dumps({"userId": "game-user-1"}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    token = f"header.{payload}.signature"
    manager = ws_module.WebSocketManager()

    connection = manager.get_connection(
        token,
        "device-1",
        wait_ready=True,
        timeout=0.5,
    )

    assert connection is not None
    assert sent
    assert json.loads(sent[0]) == {
        "event": "ping",
        "data": {"userId": "game-user-1"},
    }
    manager.close_all()
