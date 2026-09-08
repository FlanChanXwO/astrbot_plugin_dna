"""T06：App REST/官方业务 WebSocket 统一网络出口的 Red 契约。

这些测试先固定 ``AppTransport`` 的公开 seam：REST 和官方业务 WS 共用
同一个 ``proxy_url``，调用方函数名不能改变出口，外部网络调用不能继承
App 代理；错误分类则必须区分取消、断网、非 2xx、服务端响应异常以及
WebSocket close/error。实现留到 T07 Green。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Self

import aiohttp
import pytest

APP_REST_URL = "https://dnabbs-api.yingxiong.com/role/list"
APP_WS_URL = "wss://dnabbs-api.yingxiong.com:8180/ws-community-websocket"
PROXY_A = "http://proxy-a.example.test:8080"

_EXTERNAL_URLS = (
    "https://github.com/FlanChanXwO/dnaby_resources",
    "https://patch-cdn.example.test/VersionList.json",
    "https://image-cdn.example.test/role/avatar.png",
    "https://dna-login.example.test/api/login",
    "https://astrbot.example.test/api",
    "https://onebot.example.test/send_msg",
    "https://third-party-guide.example.test/role/build",
)


@dataclass(frozen=True, slots=True)
class _RequestCall:
    method: str
    url: str
    kwargs: Mapping[str, Any]


class _AsyncResult:
    """同时兼容 ``await`` 与 ``async with`` 的最小异步 fake。"""

    def __init__(self, value: Any = None, error: BaseException | None = None) -> None:
        self._value = value
        self._error = error

    async def _resolve(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._value

    def __await__(self):
        return self._resolve().__await__()

    async def __aenter__(self) -> Any:
        return await self._resolve()

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None


class _FakeResponse:
    def __init__(
        self,
        status: int,
        payload: object = None,
        *,
        json_error: BaseException | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self._json_error = json_error

    async def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeSocket:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    async def receive(self) -> object:
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        return message


class _FakeSession:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        *,
        request_error: BaseException | None = None,
        websocket: _FakeSocket | None = None,
        websocket_error: BaseException | None = None,
    ) -> None:
        self.response = response or _FakeResponse(200, {"ok": True})
        self.request_error = request_error
        self.websocket = websocket or _FakeSocket([])
        self.websocket_error = websocket_error
        self.request_calls: list[_RequestCall] = []
        self.websocket_calls: list[tuple[str, Mapping[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> _AsyncResult:
        self.request_calls.append(_RequestCall(method, url, dict(kwargs)))
        return _AsyncResult(self.response, error=self.request_error)

    def ws_connect(self, url: str, **kwargs: Any) -> _AsyncResult:
        self.websocket_calls.append((url, dict(kwargs)))
        return _AsyncResult(self.websocket, error=self.websocket_error)


def _app_transport(session: _FakeSession, *, proxy_url: str = "") -> Any:
    """延迟导入 T07 seam，使本轮 Red 能实际收集并执行所有测试。"""

    from src.infrastructure.http.app import AppTransport

    return AppTransport(
        proxy_url=proxy_url,
        session_factory=lambda: session,
    )


def _app_error_types() -> tuple[type[Exception], Any]:
    from src.infrastructure.http.app import AppTransportError, AppTransportFailureKind

    return AppTransportError, AppTransportFailureKind


def _proxy_from_call(call: _RequestCall) -> object:
    return call.kwargs.get("proxy")


def _proxy_from_websocket_call(call: tuple[str, Mapping[str, Any]]) -> object:
    return call[1].get("proxy")


@pytest.mark.asyncio
async def test_app_rest_and_business_websocket_are_direct_without_proxy() -> None:
    """空代理配置必须让 REST 与官方业务 WS 都显式直连。"""

    session = _FakeSession()
    transport = _app_transport(session)

    await transport.request_json("GET", APP_REST_URL)
    await transport.connect_websocket(APP_WS_URL)

    assert _proxy_from_call(session.request_calls[0]) is None
    assert _proxy_from_websocket_call(session.websocket_calls[0]) is None


@pytest.mark.asyncio
async def test_app_rest_and_business_websocket_share_proxy_a() -> None:
    """配置 Proxy A 后两个 App 出口必须携带同一个代理值。"""

    session = _FakeSession()
    transport = _app_transport(session, proxy_url=PROXY_A)

    await transport.request_json("POST", APP_REST_URL, json={"roleId": "role-1"})
    await transport.connect_websocket(APP_WS_URL)

    assert _proxy_from_call(session.request_calls[0]) == PROXY_A
    assert _proxy_from_websocket_call(session.websocket_calls[0]) == PROXY_A


@pytest.mark.asyncio
async def test_proxy_choice_does_not_depend_on_caller_function_name() -> None:
    """同一 transport 经不同调用函数发起请求时出口不能变化。"""

    session = _FakeSession()
    transport = _app_transport(session, proxy_url=PROXY_A)

    async def caller_a() -> None:
        await transport.request_json("GET", APP_REST_URL)

    async def caller_b() -> None:
        await transport.request_json("GET", APP_REST_URL)

    await caller_a()
    await caller_b()

    assert [_proxy_from_call(call) for call in session.request_calls] == [
        PROXY_A,
        PROXY_A,
    ]


@pytest.mark.asyncio
async def test_app_proxy_does_not_leak_to_external_network_scopes() -> None:
    """App 代理不能扩大到 GitHub、CDN、登录、AstrBot、OneBot 或攻略接口。"""

    session = _FakeSession()
    transport = _app_transport(session, proxy_url=PROXY_A)

    for url in _EXTERNAL_URLS:
        await transport.request_json("GET", url)

    assert len(session.request_calls) == len(_EXTERNAL_URLS)
    assert all(_proxy_from_call(call) is None for call in session.request_calls)


@pytest.mark.asyncio
async def test_task_cancellation_is_not_reclassified_as_network() -> None:
    """调用任务被取消时必须保留 asyncio cancellation 语义。"""

    session = _FakeSession(request_error=asyncio.CancelledError("user cancelled"))
    transport = _app_transport(session, proxy_url=PROXY_A)

    with pytest.raises(asyncio.CancelledError):
        await transport.request_json("GET", APP_REST_URL)

    assert len(session.request_calls) == 1


@pytest.mark.asyncio
async def test_rest_disconnect_maps_to_network_without_retry() -> None:
    """连接断开应归类为 network，且本契约不允许凭空重试。"""

    error_type, failure_kind = _app_error_types()
    session = _FakeSession(
        request_error=aiohttp.ClientConnectionError("connection dropped")
    )
    transport = _app_transport(session)

    with pytest.raises(error_type) as raised:
        await transport.request_json("GET", APP_REST_URL)

    assert raised.value.kind is failure_kind.NETWORK
    assert len(session.request_calls) == 1


@pytest.mark.asyncio
async def test_rest_non_2xx_maps_to_status_with_code() -> None:
    """HTTP 非 2xx 必须保留 status 分类和状态码上下文。"""

    error_type, failure_kind = _app_error_types()
    session = _FakeSession(
        _FakeResponse(503, {"message": "secret server payload"}),
    )
    transport = _app_transport(session)

    with pytest.raises(error_type) as raised:
        await transport.request_json("GET", APP_REST_URL)

    assert raised.value.kind is failure_kind.STATUS
    assert raised.value.status_code == 503
    assert "secret server payload" not in str(raised.value)
    assert len(session.request_calls) == 1


@pytest.mark.asyncio
async def test_rest_invalid_success_payload_maps_to_server() -> None:
    """2xx 但响应体无法解析时必须归类为 server，而不是空成功。"""

    error_type, failure_kind = _app_error_types()
    session = _FakeSession(
        _FakeResponse(200, json_error=ValueError("invalid JSON")),
    )
    transport = _app_transport(session)

    with pytest.raises(error_type) as raised:
        await transport.request_json("GET", APP_REST_URL)

    assert raised.value.kind is failure_kind.SERVER
    assert len(session.request_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message_type", "expected_kind"),
    [
        (aiohttp.WSMsgType.CLOSED, "WS_CLOSE"),
        (aiohttp.WSMsgType.ERROR, "WS_ERROR"),
    ],
)
async def test_websocket_close_and_error_have_distinct_transport_kinds(
    message_type: aiohttp.WSMsgType,
    expected_kind: str,
) -> None:
    """WS close 与 WS error 不能折叠成同一种 network 失败。"""

    error_type, failure_kind = _app_error_types()
    socket = _FakeSocket(
        [SimpleNamespace(type=message_type, data="opaque websocket detail")]
    )
    session = _FakeSession(websocket=socket)
    transport = _app_transport(session, proxy_url=PROXY_A)

    connected = await transport.connect_websocket(APP_WS_URL)
    with pytest.raises(error_type) as raised:
        await transport.receive_websocket(connected)

    assert raised.value.kind is getattr(failure_kind, expected_kind)
    assert "opaque websocket detail" not in str(raised.value)
