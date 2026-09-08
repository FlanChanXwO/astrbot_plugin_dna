"""二重螺旋 App REST 与官方业务 WebSocket 的统一网络 transport。

代理只由本 transport 根据目标 URL 决定：二重螺旋 App API 和官方
``ws-community-websocket`` 共用同一个 ``proxy_url``，其他网络范围始终直连。
调用方不需要、也不允许通过函数名或隐式全局配置改变出口。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

_DEFAULT_APP_HOST = "dnabbs-api.yingxiong.com"
_BUSINESS_WS_PATH = "/ws-community-websocket"


class AppTransportFailureKind(StrEnum):
    """App 网络边界可观察的失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    SERVER = "server"
    WS_CLOSE = "ws_close"
    WS_ERROR = "ws_error"


def _safe_url(url: str) -> str:
    """只保留 URL 的网络位置和路径，避免查询参数进入异常文本。"""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    if not parsed.scheme or not parsed.netloc:
        return "<invalid-url>"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class AppTransportError(RuntimeError):
    """App REST/WS transport 失败的安全载体。

    ``detail`` 仅供内部诊断，异常字符串固定为类别摘要；服务端响应体、查询
    参数以及 WebSocket 原始 close/error 文本不会被拼入用户可见异常。
    """

    def __init__(
        self,
        kind: AppTransportFailureKind | str,
        *,
        method: str = "",
        url: str = "",
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        self.kind = AppTransportFailureKind(kind)
        self.method = method.upper()
        self.url = _safe_url(url)
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"app transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """repr 只保留类别和状态码，不序列化响应原文。"""

        suffix = (
            f", status_code={self.status_code!r}"
            if self.status_code is not None
            else ""
        )
        return f"AppTransportError(kind={self.kind.value!r}{suffix})"


class AppTransport:
    """统一承载 App REST 与官方业务 WebSocket 的异步 HTTP 边界。"""

    def __init__(
        self,
        *,
        proxy_url: str = "",
        api_base_url: str = "",
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.proxy_url = proxy_url.strip()
        self.api_base_url = api_base_url.strip().rstrip("/")
        self._session_factory = session_factory or self._default_session_factory
        self._session: Any | None = None
        self._session_lock = asyncio.Lock()

    @staticmethod
    def _default_session_factory() -> aiohttp.ClientSession:
        """创建不附带固定业务超时的客户端；取消由调用任务负责传播。"""

        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True),
        )

    def set_network(self, *, proxy_url: str = "", api_base_url: str = "") -> None:
        """更新后续请求使用的网络配置，不重建调用方持有的 transport。"""

        self.proxy_url = proxy_url.strip()
        self.api_base_url = api_base_url.strip().rstrip("/")

    @staticmethod
    def _hostname(url: str) -> str | None:
        try:
            return (urlsplit(url).hostname or "").lower() or None
        except ValueError:
            return None

    def _app_hosts(self) -> frozenset[str]:
        hosts = {_DEFAULT_APP_HOST}
        configured = self._hostname(self.api_base_url)
        if configured is not None:
            hosts.add(configured)
        return frozenset(hosts)

    def _is_app_rest_url(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        return (
            parsed.scheme in {"http", "https"} and parsed.hostname in self._app_hosts()
        )

    def _is_business_websocket_url(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        return (
            parsed.scheme in {"ws", "wss"}
            and parsed.hostname in self._app_hosts()
            and parsed.path.rstrip("/") == _BUSINESS_WS_PATH
        )

    def _proxy_for(self, url: str) -> str | None:
        """只给 App REST/官方业务 WS 返回配置代理，其他范围显式直连。"""

        if self.proxy_url and (
            self._is_app_rest_url(url) or self._is_business_websocket_url(url)
        ):
            return self.proxy_url
        return None

    def _resolve_url(self, url: str) -> str:
        """把官方 App 路径映射到可选的兼容 API base URL。"""

        if not self.api_base_url or not self._is_app_rest_url(url):
            return url
        try:
            target = urlsplit(url)
            base = urlsplit(self.api_base_url)
        except ValueError:
            return url
        if not target.path or not base.scheme or not base.netloc:
            return url
        base_path = base.path.rstrip("/")
        target_path = "/" + target.path.lstrip("/")
        return urlunsplit(
            (
                base.scheme,
                base.netloc,
                f"{base_path}{target_path}",
                target.query,
                target.fragment,
            )
        )

    @staticmethod
    def _session_is_closed(session: Any) -> bool:
        return bool(getattr(session, "closed", False))

    async def _get_session(self) -> Any:
        session = self._session
        if session is not None and not self._session_is_closed(session):
            return session

        async with self._session_lock:
            session = self._session
            if session is not None and not self._session_is_closed(session):
                return session
            session = self._session_factory()
            if hasattr(session, "__await__"):
                session = await session
            self._session = session
            return session

    def _error(
        self,
        kind: AppTransportFailureKind,
        *,
        method: str,
        url: str,
        status_code: int | None = None,
        detail: str = "",
    ) -> AppTransportError:
        return AppTransportError(
            kind,
            method=method,
            url=url,
            status_code=status_code,
            detail=detail,
        )

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: object | None = None,
        data: object | None = None,
    ) -> object:
        """发送一次 App REST 请求并返回 JSON payload。

        该边界不自行重试，也不设置固定业务超时；调用任务取消时保留
        ``asyncio.CancelledError``，请求失败则显式映射为 transport error。
        """

        resolved_url = self._resolve_url(url)
        proxy = self._proxy_for(resolved_url)
        try:
            session = await self._get_session()
            async with session.request(
                method,
                resolved_url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                proxy=proxy,
            ) as response:
                status = getattr(response, "status", None)
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise self._error(
                        AppTransportFailureKind.STATUS,
                        method=method,
                        url=resolved_url,
                        status_code=status if isinstance(status, int) else None,
                        detail="non-2xx response",
                    )
                try:
                    return await response.json()
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001
                    raise self._error(
                        AppTransportFailureKind.SERVER,
                        method=method,
                        url=resolved_url,
                        detail=f"JSON decode failed: {type(error).__name__}",
                    ) from None
        except AppTransportError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._error(
                AppTransportFailureKind.NETWORK,
                method=method,
                url=resolved_url,
                detail=f"request failed: {type(error).__name__}",
            ) from None

    async def connect_websocket(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """建立一次 WebSocket 连接；代理策略与 REST 完全共用。"""

        resolved_url = self._resolve_url(url)
        proxy = self._proxy_for(resolved_url)
        # 出口策略属于 transport，忽略调用方试图覆盖的 proxy 参数。
        kwargs.pop("proxy", None)
        try:
            session = await self._get_session()
            return await session.ws_connect(
                resolved_url,
                headers=headers,
                proxy=proxy,
                **kwargs,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._error(
                AppTransportFailureKind.NETWORK,
                method="WS",
                url=resolved_url,
                detail=f"websocket connect failed: {type(error).__name__}",
            ) from None

    async def receive_websocket(self, socket: Any) -> Any:
        """读取一帧并区分 close 与 error。"""

        try:
            message = await socket.receive()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._error(
                AppTransportFailureKind.WS_ERROR,
                method="WS",
                url="",
                detail=f"websocket receive failed: {type(error).__name__}",
            ) from None

        message_type = getattr(message, "type", None)
        if message_type == aiohttp.WSMsgType.CLOSED:
            raise self._error(
                AppTransportFailureKind.WS_CLOSE,
                method="WS",
                url="",
                detail="websocket closed",
            )
        if message_type == aiohttp.WSMsgType.ERROR:
            raise self._error(
                AppTransportFailureKind.WS_ERROR,
                method="WS",
                url="",
                detail="websocket error",
            )
        return message

    async def close(self) -> None:
        """关闭 transport 持有的 HTTP session。"""

        session = self._session
        self._session = None
        if session is None:
            return
        close = getattr(session, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result


__all__ = [
    "AppTransport",
    "AppTransportError",
    "AppTransportFailureKind",
]
