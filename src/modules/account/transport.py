from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from astrbot.api import logger
from pydantic import BaseModel, ConfigDict, Field

from .contracts import LoginChannel

START_TIMEOUT_S = 10.0
POLL_INTERVAL_S = 2.0
LOGIN_TTL_S = 600


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportResult:
    status: str  # success | failed | expired | cancelled
    channel: LoginChannel = LoginChannel.APP
    msg: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    dev_code: str = field(default="", repr=False)
    d_num: str = field(default="", repr=False)
    refresh_token: str = field(default="", repr=False)


class TransportError(RuntimeError):
    pass


class _ProtocolModel(BaseModel):
    """dna-login 服务回执的解析基类。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class _Credential(_ProtocolModel):
    token: str = Field(description="皎皎角 token")
    dev_code: str = Field(description="登录时使用的设备码")
    channel: LoginChannel = Field(
        default=LoginChannel.APP,
        description="登录来源，旧服务未返回时按 App 处理",
    )
    d_num: str = Field(default="", description="皎皎角 dNum")
    refresh_token: str = Field(default="", description="皎皎角 refreshToken")


class _StatusModel(_ProtocolModel):
    status: str = Field(description="pending / success / failed / expired / heartbeat")
    msg: str = Field(default="", description="给用户看的展示文案")
    credential: _Credential | None = Field(
        default=None, description="终态为 success 时的凭据"
    )


def _parse_status_payload(raw: str) -> _StatusModel:
    """解析外置回执，并把可能含凭据的解析原文隔离在异常链之外。"""

    try:
        return _StatusModel.model_validate(json.loads(raw))
    except (TypeError, ValueError):
        raise TransportError("外置登录服务回执格式错误") from None


class LoginTransport(Protocol):
    async def start(
        self,
        *,
        auth: str,
        user_id: str,
        bot_id: str,
        group_id: str | None,
    ) -> str: ...

    async def listen(self, auth: str) -> TransportResult | None: ...


def _sign(parts: list[str], shared_secret: str = "") -> str:
    """使用调用方注入的共享密钥签名，不读取 legacy 全局配置。"""

    secret = shared_secret.strip()
    if not secret:
        return ""
    return hmac.new(
        secret.encode(), "|".join(parts).encode(), hashlib.sha256
    ).hexdigest()


def _to_result(payload: _StatusModel) -> TransportResult | None:
    """终态才返回 TransportResult；pending / heartbeat 等中间态返回 None。"""
    if payload.status not in {"success", "failed", "expired", "cancelled"}:
        return None
    cred = payload.credential
    if cred is None:
        return TransportResult(
            status=payload.status,
            msg=payload.msg,
        )
    if cred.channel is not LoginChannel.APP:
        raise TransportError("外置登录服务仅支持 App 登录回执")
    return TransportResult(
        status=payload.status,
        channel=cred.channel,
        msg=payload.msg,
        token=cred.token,
        dev_code=cred.dev_code,
        d_num=cred.d_num,
        refresh_token=cred.refresh_token,
    )


def _normalize_base_url(raw: str) -> str:
    """没带 scheme 自动补 https；尾斜杠去掉。"""
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return raw


class _Base:
    def __init__(self, base_url: str, shared_secret: str = ""):
        self.base_url = _normalize_base_url(base_url)
        self.shared_secret = shared_secret.strip()

    async def start(
        self,
        *,
        auth: str,
        user_id: str,
        bot_id: str,
        group_id: str | None,
    ) -> str:
        ts = int(time.time())
        body = {
            "auth": auth,
            "user_id": user_id,
            "bot_id": bot_id,
            "group_id": group_id,
            "ts": ts,
            "sig": _sign(["start", auth, user_id, str(ts)], self.shared_secret),
        }
        url = f"{self.base_url}/dna/start"
        logger.debug("[DNA登录] 外置登录服务 start 请求")
        try:
            async with httpx.AsyncClient(
                timeout=START_TIMEOUT_S, trust_env=False
            ) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as err:
            raise TransportError("外置登录服务网络错误") from err

        if resp.status_code != 200:
            raise TransportError(f"外置登录服务 start 返回 HTTP {resp.status_code}")

        return f"{self.base_url}/dna/i/{auth}"


class HttpPollTransport(_Base):
    async def listen(self, auth: str) -> TransportResult | None:
        waited_s = 0.0
        last_network_error: httpx.HTTPError | None = None
        async with httpx.AsyncClient(
            timeout=START_TIMEOUT_S, trust_env=False
        ) as client:
            while waited_s < LOGIN_TTL_S:
                ts = int(time.time())
                params = {
                    "ts": ts,
                    "sig": _sign(["listen", auth, str(ts)], self.shared_secret),
                }
                try:
                    resp = await client.get(
                        f"{self.base_url}/dna/status/{auth}", params=params
                    )
                except httpx.HTTPError as err:
                    logger.debug(
                        f"[DNA登录] poll 网络错误，将重试: {type(err).__name__}",
                    )
                    last_network_error = err
                    await asyncio.sleep(POLL_INTERVAL_S)
                    waited_s += POLL_INTERVAL_S
                    continue
                if resp.status_code != 200:
                    raise TransportError(f"poll 返回 HTTP {resp.status_code}")

                payload = _parse_status_payload(resp.text)
                last_network_error = None
                terminal = _to_result(payload)
                if terminal is not None:
                    return terminal
                await asyncio.sleep(POLL_INTERVAL_S)
                waited_s += POLL_INTERVAL_S
        if last_network_error is not None:
            raise TransportError(
                "poll 网络错误，登录状态无法确认"
            ) from last_network_error
        return None


class SseTransport(_Base):
    async def listen(self, auth: str) -> TransportResult | None:
        ts = int(time.time())
        params = {
            "ts": ts,
            "sig": _sign(["listen", auth, str(ts)], self.shared_secret),
        }
        url = f"{self.base_url}/dna/events/{auth}"
        timeout = httpx.Timeout(LOGIN_TTL_S, connect=START_TIMEOUT_S)
        try:
            async with asyncio.timeout(LOGIN_TTL_S):
                async with httpx.AsyncClient(
                    timeout=timeout, trust_env=False
                ) as client:
                    async with client.stream("GET", url, params=params) as response:
                        if response.status_code != 200:
                            raise TransportError(
                                f"SSE 握手失败 HTTP {response.status_code}"
                            )
                        return await self._consume_sse(response)
        except TimeoutError:
            return None
        except httpx.HTTPError as err:
            raise TransportError("SSE 网络错误") from err

    @staticmethod
    async def _consume_sse(response: httpx.Response) -> TransportResult | None:
        buffer: list[str] = []
        async for line in response.aiter_lines():
            if line.startswith(":"):
                continue
            if line == "":
                if not buffer:
                    continue
                raw = "".join(buffer)
                buffer.clear()
                payload = _parse_status_payload(raw)
                terminal = _to_result(payload)
                if terminal is not None:
                    return terminal
                continue
            if line.startswith("data:"):
                buffer.append(line[5:].lstrip())
        return None


class WsTransport(_Base):
    async def listen(self, auth: str) -> TransportResult | None:
        try:
            from websockets.asyncio.client import connect
        except ImportError as err:
            raise TransportError("ws 模式需要安装 `websockets` 库") from err

        ts = int(time.time())
        ws_base = self.base_url.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
        url = (
            f"{ws_base}/dna/ws/{auth}?ts={ts}&sig="
            f"{_sign(['listen', auth, str(ts)], self.shared_secret)}"
        )

        try:
            async with asyncio.timeout(LOGIN_TTL_S):
                async with connect(url, open_timeout=START_TIMEOUT_S, proxy=None) as ws:
                    async for raw in ws:
                        payload = _parse_status_payload(raw)
                        terminal = _to_result(payload)
                        if terminal is not None:
                            return terminal
        except TimeoutError:
            return None
        except OSError as err:
            raise TransportError("ws 连接失败") from err
        return None


_TRANSPORTS: dict[str, Callable[[str, str], LoginTransport]] = {
    "http_poll": HttpPollTransport,
    "sse": SseTransport,
    "ws": WsTransport,
}


def build_transport(
    base_url: str,
    transport: str = "http_poll",
    shared_secret: str = "",
) -> LoginTransport:
    """按 typed 配置创建外置登录 transport。"""

    name = transport.strip()
    factory = _TRANSPORTS.get(name)
    if factory is None:
        raise TransportError(
            f"未知 transport：{name}（可选：{', '.join(_TRANSPORTS)}）"
        )
    return factory(base_url, shared_secret)
