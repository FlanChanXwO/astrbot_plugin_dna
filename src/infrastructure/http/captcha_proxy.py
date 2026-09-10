"""验证码会话的 UA 反代。

背景（DNA-analysis ``docs/login-248/10`` 的实测结论）：Windows 浏览器上
``getSmsCode`` 返回 ``248`` 的唯一判别变量是发给 ``*.alicaptcha.com`` 请求的
HTTP ``User-Agent`` 平台标识。页面 JS 无权修改该头（浏览器规范），因此浏览器
侧经 Service Worker / 页面钩子把验证码请求重写到本插件同源路由，由这里把
``User-Agent`` 与 UA-CH 固定为官方 App 场景的 Android 画像后再转发上游。

安全边界：只允许转发到白名单内的 alicaptcha 域名，不构成开放代理；除白名单
安全头外不透传任何浏览器头；日志只记录错误类别，不记录 URL、请求体或响应体。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from astrbot.api import logger

# 与 transport.START_TIMEOUT_S 保持一致的外呼短超时约定：这些端点是用户
# 交互链路（滑块/发码）的实时请求，失败应快速返回以便用户重试。
PROXY_TIMEOUT_S = 10.0

# 转发上游白名单：仅 Alicom 真实会话涉及的三台主机（fp-diag 实测覆盖集）。
UPSTREAM_HOSTS: dict[str, str] = {
    "captcha.alicaptcha.com": "https://captcha.alicaptcha.com",
    "captchabak.alicaptcha.com": "https://captchabak.alicaptcha.com",
    "static.alicaptcha.com": "https://static.alicaptcha.com",
}

# Android 转发画像：与官方 App 上下文一致，fp-diag 实测 getSmsCode 返回 200。
ANDROID_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; V2304A) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
SEC_CH_UA_PLATFORM = '"Android"'
SEC_CH_UA_MOBILE = "?1"

# Alicom 会校验 Referer/Origin；固定为官方 H5 来源（与 fp-diag 实测一致）。
REFERER = "https://dnabbs.yingxiong.com/"
ORIGIN = "https://dnabbs.yingxiong.com"


class CaptchaProxyError(RuntimeError):
    """反代上游网络层失败；不带上游正文，避免泄露细节。"""


@dataclass(frozen=True, slots=True)
class ProxyResult:
    """上游响应的最小映射：状态码、内容类型与字节体。"""

    status: int
    content_type: str
    body: bytes


def build_upstream_url(host: str, path: str, query: str) -> str | None:
    """拼接上游地址；host 不在白名单时返回 ``None``。

    ``query`` 按原始字节级透传（由调用方给出未解码的 query string），
    白名单域名以外的任何请求都不产生网络行为。
    """

    origin = UPSTREAM_HOSTS.get(host.strip().lower())
    if origin is None:
        return None
    url = f"{origin}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    return url


def build_forward_headers(
    incoming: Mapping[str, str],
    *,
    method: str,
) -> dict[str, str]:
    """构造发给上游的请求头：注入 Android 画像，只透传白名单安全头。

    浏览器自身的 ``User-Agent``、Cookie 和其余头部一律不透传——UA 是 248
    的判别对象，其余头部既可能穿帮也可能携带用户凭据。
    """

    headers = {
        "User-Agent": ANDROID_USER_AGENT,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "Accept": incoming.get("Accept", "*/*"),
        "Accept-Language": incoming.get("Accept-Language", "zh-CN,zh;q=0.9"),
        "Referer": REFERER,
        "Origin": ORIGIN,
    }
    if method.upper() not in {"GET", "HEAD"}:
        headers["Content-Type"] = incoming.get(
            "Content-Type", "application/x-www-form-urlencoded"
        )
    return headers


def new_http_client() -> httpx.AsyncClient:
    """按项目统一惯例创建出站客户端（``trust_env=False`` 避免代理环境串扰）。"""

    return httpx.AsyncClient(timeout=PROXY_TIMEOUT_S, trust_env=False)


async def forward(
    host: str,
    path: str,
    query: str,
    method: str,
    incoming_headers: Mapping[str, str],
    body: bytes,
    *,
    client: httpx.AsyncClient,
) -> ProxyResult | None:
    """把一次验证码请求转发到上游；host 非白名单时返回 ``None``。

    网络层错误（连接失败、超时等）统一抛 ``CaptchaProxyError``；上游返回的
    HTTP 错误状态码本身属于有效响应，原样映射给调用方。
    """

    url = build_upstream_url(host, path, query)
    if url is None:
        return None
    headers = build_forward_headers(incoming_headers, method=method)
    try:
        response = await client.request(
            method,
            url,
            headers=headers,
            content=body or None,
        )
    except httpx.HTTPError as error:
        logger.warning(
            "验证码反代上游请求失败 kind=%s",
            type(error).__name__,
        )
        raise CaptchaProxyError("验证码服务网络错误") from error
    return ProxyResult(
        status=response.status_code,
        # httpx 已按 Content-Encoding 解码 body，这里只回传原始内容类型。
        content_type=response.headers.get("Content-Type", "application/octet-stream"),
        body=response.content,
    )


__all__ = [
    "ANDROID_USER_AGENT",
    "PROXY_TIMEOUT_S",
    "UPSTREAM_HOSTS",
    "CaptchaProxyError",
    "ProxyResult",
    "build_forward_headers",
    "build_upstream_url",
    "forward",
    "new_http_client",
]
