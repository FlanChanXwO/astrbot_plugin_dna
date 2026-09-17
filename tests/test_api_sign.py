"""请求签名异步边界回归测试。"""

from __future__ import annotations

import inspect
import threading

import pytest

from src.utils.api import sign as sign_module
from src.utils.api import ws_manager as ws_module


@pytest.mark.asyncio
async def test_signed_request_waits_for_websocket_off_event_loop(monkeypatch) -> None:
    """WebSocket 就绪等待不得在 asyncio 事件循环线程执行。"""

    event_loop_thread = threading.get_ident()
    connection_threads: list[int] = []

    class _WebSocketManager:
        def get_connection(self, *_args, **_kwargs):
            connection_threads.append(threading.get_ident())
            return object()

    monkeypatch.setattr(ws_module, "get_ws_manager", lambda: _WebSocketManager())
    monkeypatch.setattr(ws_module, "get_ws_wait_time", lambda: 5)
    monkeypatch.setattr(
        sign_module,
        "generate_headers_130",
        lambda header, data, _rsa_public_key: (header, data),
    )

    result = sign_module.get_signed_headers_and_body(
        url="https://example.invalid/user/signIn",
        header={"token": "token", "devCode": "device"},
        data={},
        rsa_public_key="unused",
    )
    if inspect.isawaitable(result):
        await result

    assert connection_threads
    assert connection_threads[0] != event_loop_thread
