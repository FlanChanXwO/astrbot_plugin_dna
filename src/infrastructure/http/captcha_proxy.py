"""验证码会话的 UA 反代。

背景（DNA-analysis ``docs/login-248/10`` 的实测结论）：Windows 浏览器上
``getSmsCode`` 返回 ``248`` 的唯一判别变量是发给 ``*.alicaptcha.com`` 请求的
HTTP ``User-Agent`` 平台标识。页面 JS 无权修改该头（浏览器规范），因此浏览器
侧经 Service Worker / 页面钩子把验证码请求重写到本插件同源路由，由这里把
``User-Agent`` 与 UA-CH 固定为官方 App 场景的 Android 画像后再转发上游。

安全边界：只允许转发到白名单内的 alicaptcha 域名，不构成开放代理；除白名单
安全头外不透传任何浏览器头；上游跳转只允许落到白名单主机；日志只记录错误类别，
不记录 URL、请求体或响应体。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from astrbot.api import logger

# 出站建连预算：TCP 建连到不可达主机时会一直等到操作系统默认超时（macOS 约
# 75s），期间用户交互请求被白白挂起，因此沿用项目既有外呼的 10s 建连约定
# （``transport.START_TIMEOUT_S``）作为接入上限。
# 只限制建连、不限制读取：验证码请求由用户交互触发，上游响应较慢时应等待真实
# 结果，而不是把慢响应在本地转换成本不存在的 502 假失败；用户关闭页面即可中止。
PROXY_CONNECT_TIMEOUT_S = 10.0

# 需要在本地重写 Location 的跳转状态码。
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

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
    """上游响应的最小映射：状态码、内容类型与字节体。

    ``location`` 只可能在 ``status`` 属于 ``REDIRECT_STATUSES`` 时有值，且已经
    过白名单校验并重写为本地同源反代地址；跳转目标不在白名单时为 ``None``，
    由调用方明确拒绝而不是把请求链带出白名单。
    """

    status: int
    content_type: str
    body: bytes
    location: str | None = None


def parse_proxy_target(
    raw_path: str,
    *,
    prefix: str,
) -> tuple[str, str, str] | None:
    """把原始（未解码）请求路径拆成 ``(auth, host, raw_subpath)``。

    只能用 aiohttp 收到的原始请求行：解码后的路径会把 ``%2F``、``%23`` 等
    还原成字面字符，重新拼回上游 URL 时会截断或改写验证码参数。``prefix``
    形如 ``/astrbot_plugin_dna/alicap/``；前缀缺失、缺段或段为空时返回
    ``None``，由调用方明确拒绝，而不是转发一个来路不明的路径。

    ``host`` 保持原始字节不做解码：白名单是固定 ASCII 域名，任何编码变体都
    应当在白名单判定处被当作不匹配。
    """

    if not raw_path.startswith(prefix):
        return None
    auth, separator, remainder = raw_path[len(prefix) :].partition("/")
    if not separator or not auth:
        return None
    host, separator, sub_path = remainder.partition("/")
    if not separator or not host:
        return None
    return auth, host, sub_path


def build_upstream_url(host: str, path: str, query: str) -> str | None:
    """拼接上游地址；host 不在白名单时返回 ``None``。

    ``path`` 与 ``query`` 由调用方按原始字节给出（不经过 URL 解码），
    ``httpx`` 会保留其中的百分号编码，实现字节级透传。白名单域名以外的任何
    请求都不产生网络行为。
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


def rewrite_redirect(
    location: str,
    *,
    base: httpx.URL,
    proxy_prefix: str,
) -> str | None:
    """校验上游 ``Location`` 并重写为本地同源反代地址。

    只接受解析后 host 落在 ``UPSTREAM_HOSTS``、协议为 https 且端口为默认 443
    的绝对地址，相对跳转按 ``base`` 解析。目标不在白名单、协议或端口异常、原始
    路径含非 ASCII 字节时返回 ``None``，由调用方拒绝，避免跟随跳转绕过 host
    白名单。
    """

    if not location.strip():
        return None
    try:
        target = base.join(location.strip())
    except (httpx.InvalidURL, ValueError):
        return None
    host = (target.host or "").strip().lower()
    # 白名单条目都是 443 上的规范 origin；同主机其它端口不在白名单内，
    # 不能被同名主机的跳转悄悄带到别的服务。
    if target.scheme != "https" or host not in UPSTREAM_HOSTS:
        return None
    if target.port not in (None, 443):
        return None
    try:
        raw_path = target.raw_path.decode("ascii")
    except UnicodeDecodeError:
        return None
    return f"{proxy_prefix}{host}{raw_path}"


def new_http_client() -> httpx.AsyncClient:
    """按项目统一惯例创建出站客户端（``trust_env=False`` 避免代理环境串扰）。

    不跟随上游跳转：跟随会让上游把请求带到白名单之外的域名。跳转由
    ``forward`` 校验后重写回本地反代，仍受同一份白名单约束。
    """

    return httpx.AsyncClient(
        timeout=httpx.Timeout(PROXY_CONNECT_TIMEOUT_S, read=None),
        trust_env=False,
        follow_redirects=False,
    )


async def forward(
    host: str,
    path: str,
    query: str,
    method: str,
    incoming_headers: Mapping[str, str],
    body: bytes,
    *,
    client: httpx.AsyncClient,
    proxy_prefix: str,
) -> ProxyResult | None:
    """把一次验证码请求转发到上游；host 非白名单时返回 ``None``。

    网络层错误（连接失败、超时等）统一抛 ``CaptchaProxyError``；上游返回的
    HTTP 错误状态码本身属于有效响应，原样映射给调用方。3xx 跳转只在目标仍属
    白名单时重写为 ``proxy_prefix`` 下的本地地址，否则 ``location`` 为 ``None``。
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
    location: str | None = None
    if response.status_code in REDIRECT_STATUSES:
        location = rewrite_redirect(
            response.headers.get("Location", ""),
            base=httpx.URL(url),
            proxy_prefix=proxy_prefix,
        )
        if location is None:
            # 只记录类别，不记录可能含签名的跳转地址。
            logger.warning("验证码反代跳转目标不在白名单 kind=redirect")
    return ProxyResult(
        status=response.status_code,
        # httpx 已按 Content-Encoding 解码 body，这里只回传原始内容类型。
        content_type=response.headers.get("Content-Type", "application/octet-stream"),
        body=response.content,
        location=location,
    )


__all__ = [
    "ANDROID_USER_AGENT",
    "PROXY_CONNECT_TIMEOUT_S",
    "REDIRECT_STATUSES",
    "UPSTREAM_HOSTS",
    "CaptchaProxyError",
    "ProxyResult",
    "build_forward_headers",
    "build_upstream_url",
    "parse_proxy_target",
    "forward",
    "new_http_client",
    "rewrite_redirect",
]
