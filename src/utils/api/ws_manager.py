import base64
import binascii
import json
import ssl
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import unquote, urlsplit

import websocket
from astrbot.api import logger

from .request_util import ios_base_header

_configured_continue_seconds: int | None = None
_configured_wait_seconds: int | None = None


def get_ws_continue_time() -> int:
    if _configured_continue_seconds is not None:
        return _configured_continue_seconds

    from ...infrastructure.config.settings import DNAConfig

    try:
        return DNAConfig.get_config("WebSocketContinueTime").data or 300
    except KeyError:
        return 300


def get_ws_wait_time() -> int:
    if _configured_wait_seconds is not None:
        return _configured_wait_seconds

    from ...infrastructure.config.settings import DNAConfig

    try:
        return DNAConfig.get_config("WebSocketWaitTime").data or 5
    except KeyError:
        return 5


class WebSocketManager:
    """WebSocket 连接池管理器

    心跳：业务层心跳（每10秒发送 {"event": "ping", "data": {"userId": ...}}）
    """

    WS_URL = "wss://dnabbs-api.yingxiong.com:8180/ws-community-websocket"
    MAX_POOL_SIZE = 20
    HEARTBEAT_INTERVAL = 10

    def __init__(self, proxy_url: str = ""):
        self.proxy_url = proxy_url.strip()
        # _pool 存储 (ws, timestamp) 元组
        self._pool: OrderedDict[tuple[str, str], tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._ready_events: dict[tuple[str, str], threading.Event] = {}

    def set_proxy_url(self, proxy_url: str = "") -> None:
        """更新后续官方业务 WebSocket 握手的代理。"""

        self.proxy_url = proxy_url.strip()

    def _proxy_options(self) -> dict[str, Any]:
        """转换统一 proxy URL 为 websocket-client 的显式连接选项。"""

        if not self.proxy_url:
            # websocket-client 默认会读取进程环境代理；显式通配 no_proxy
            # 才能让“直连”配置不被宿主环境中的代理变量改变。
            return {"http_no_proxy": ["*"]}

        parsed = urlsplit(self.proxy_url)
        if not parsed.hostname:
            raise ValueError("proxy URL 缺少主机名")
        scheme = parsed.scheme.lower()
        if scheme in {"http", "https"}:
            proxy_type = "http"
            default_port = 443 if scheme == "https" else 80
        elif scheme in {"socks4", "socks4a", "socks5", "socks5h"}:
            proxy_type = scheme
            default_port = 1080
        else:
            raise ValueError("不支持的 WebSocket 代理协议")

        options: dict[str, Any] = {
            "http_proxy_host": parsed.hostname,
            "http_proxy_port": parsed.port or default_port,
            "proxy_type": proxy_type,
        }
        if parsed.username is not None:
            options["http_proxy_auth"] = (
                unquote(parsed.username),
                unquote(parsed.password or ""),
            )
        return options

    def _extract_user_id(self, token: str) -> str:
        try:
            if len(parts := token.split(".")) >= 2:
                payload = parts[1]
                if padding := len(payload) % 4:
                    payload += "=" * (4 - padding)
                if data := json.loads(base64.urlsafe_b64decode(payload)):
                    return str(data.get("userId", ""))
        except (
            binascii.Error,
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            ValueError,
        ) as error:
            logger.debug(f"[DNA WebSocket] token 解析失败: {error}")
        return ""

    def _start_heartbeat(self, ws: Any, user_id: str):
        def heartbeat_loop():
            while True:
                time.sleep(self.HEARTBEAT_INTERVAL)
                try:
                    if ws.sock and ws.sock.connected:
                        ws.send(
                            json.dumps({"event": "ping", "data": {"userId": user_id}})
                        )
                    else:
                        break
                except (OSError, websocket.WebSocketException):
                    break

        threading.Thread(target=heartbeat_loop, daemon=True).start()

    def _create_connection(
        self, token: str, dev_code: str, ready_event: threading.Event
    ) -> Any | None:
        try:
            key = (token, dev_code)
            user_id = self._extract_user_id(token)

            def _remove_from_pool():
                with self._lock:
                    self._pool.pop(key, None)
                    self._ready_events.pop(key, None)

            def on_message(ws, message):
                # 快速过期检查
                logger.debug(f"[DNA WebSocket] received message: {message}")
                with self._lock:
                    if (item := self._pool.get(key)) and time.time() - item[
                        1
                    ] > get_ws_continue_time():
                        try:
                            ws.close()
                        except (OSError, websocket.WebSocketException) as error:
                            logger.debug(f"[DNA WebSocket] 关闭过期连接失败: {error}")

            def on_error(ws, error):
                logger.debug(f"[DNA WebSocket] on_error is called (error: {error})")
                _remove_from_pool()
                ready_event.set()  # 即使出错也要释放等待

            def on_close(ws, close_status_code, close_msg):
                logger.debug(
                    f"[DNA WebSocket] on_close is called (code: {close_status_code}, message: {close_msg})"
                )
                _remove_from_pool()

            def on_open(ws):
                logger.debug("[DNA WebSocket] on_open is successed")
                with self._lock:
                    self._pool[key] = (ws, time.time())
                self._start_heartbeat(ws, user_id)
                ready_event.set()  # 连接成功，释放等待

            ws = websocket.WebSocketApp(
                self.WS_URL,
                header=[
                    f"{k}:{v}"
                    for k, v in {
                        "sourse": "ios",
                        "appVersion": ios_base_header.get("version", "1.2.0"),
                        "token": token,
                        "devCode": dev_code,
                    }.items()
                ],
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            run_options = {
                "sslopt": {"cert_reqs": ssl.CERT_NONE},
                **self._proxy_options(),
            }
            threading.Thread(
                target=lambda: ws.run_forever(**run_options),
                daemon=True,
            ).start()
            return ws
        except (OSError, TypeError, ValueError, websocket.WebSocketException) as e:
            logger.warning(f"[DNA WebSocket] connection failed (error: {e})")
            ready_event.set()
            return None

    def _is_expired(self, key: tuple[str, str]) -> bool:
        if not (item := self._pool.get(key)):
            return True
        return time.time() - item[1] > get_ws_continue_time()

    def _cleanup_connection(self, key: tuple[str, str]):
        if item := self._pool.pop(key, None):
            try:
                item[0].close()
            except (OSError, websocket.WebSocketException) as error:
                logger.debug(f"[DNA WebSocket] 清理连接失败: {error}")

    def get_connection(
        self, token: str, dev_code: str, wait_ready: bool = False, timeout: float = 5
    ) -> Any | None:
        if not token or not dev_code:
            return None
        key = (token, dev_code)

        with self._lock:
            # 检查连接是否存在且有效（未过期）
            if (item := self._pool.get(key)) and time.time() - item[
                1
            ] <= get_ws_continue_time():
                # 续时：更新时间戳以延长连接过期时间
                self._pool[key] = (item[0], time.time())
                self._pool.move_to_end(key)
                return item[0]

            # 清理当前请求的无效连接
            if key in self._pool:
                self._cleanup_connection(key)

            # 批量清理其他过期连接
            for expired_key in [k for k in self._pool if self._is_expired(k)]:
                self._cleanup_connection(expired_key)

            # LRU 淘汰：超过上限则移除最老的
            while len(self._pool) >= self.MAX_POOL_SIZE:
                self._cleanup_connection(self._pool.popitem(last=False)[0])

            # 创建新连接
            ready_event = threading.Event()
            self._ready_events[key] = ready_event

            ws = self._create_connection(token, dev_code, ready_event)
            if not ws:
                self._ready_events.pop(key, None)
                return None

            self._pool[key] = (ws, time.time())  # on_open 会更新为实际建立时间

        # 等待连接建立
        if wait_ready:
            logger.debug(
                f"[DNA WebSocket] waiting for connection to be established (timeout {timeout}s)..."
            )
            if ready_event.wait(timeout):
                with self._lock:
                    if key in self._pool:
                        logger.debug("[DNA WebSocket] connection is ready")
                        return self._pool[key][0]
                    else:
                        logger.warning("[DNA WebSocket] connection is failed")
                        return None
            else:
                logger.warning(
                    f"[DNA WebSocket] waiting for connection to be established timeout ({timeout}s)"
                )
                # 超时后清理连接
                with self._lock:
                    self._cleanup_connection(key)
                    self._ready_events.pop(key, None)
                return None

        return ws

    def get_active_tokens(self, limit: int | None = 3) -> list[tuple[str, str]]:
        with self._lock:
            current_time = time.time()
            active_tokens = []
            for key, item in self._pool.items():
                if current_time - item[1] <= get_ws_continue_time():
                    token, dev_code = key
                    active_tokens.append((token, dev_code))
                    if limit is not None and len(active_tokens) >= limit:
                        break
            return active_tokens

    def close_all(self):
        with self._lock:
            while self._pool:
                _, item = self._pool.popitem()
                try:
                    item[0].close()
                except (OSError, websocket.WebSocketException) as error:
                    logger.debug(f"[DNA WebSocket] 关闭连接失败: {error}")


# 全局单例
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    global _ws_manager
    return _ws_manager or (_ws_manager := WebSocketManager())


def configure_ws_manager(
    *,
    proxy_url: str = "",
    continue_seconds: int | None = None,
    wait_seconds: int | None = None,
) -> WebSocketManager:
    """把 typed network 配置应用到官方业务 WebSocket 管理器。"""

    global _configured_continue_seconds, _configured_wait_seconds
    manager = get_ws_manager()
    manager.set_proxy_url(proxy_url)
    if continue_seconds is not None:
        _configured_continue_seconds = continue_seconds
    if wait_seconds is not None:
        _configured_wait_seconds = wait_seconds
    return manager
