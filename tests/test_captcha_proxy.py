"""验证码反代：host 白名单、Android 画像注入与请求/响应透传行为。

248 的判别发生在发给 ``*.alicaptcha.com`` 请求的 HTTP ``User-Agent``
平台标识；反代必须把 UA/UA-CH 固定为实测过 Android 画像，并字节级透传
query 与 body。具体证据见 DNA-analysis ``docs/login-248/10``。
"""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest

from src.infrastructure.config.settings import LoginSettings
from src.infrastructure.http import captcha_proxy
from src.infrastructure.http.captcha_proxy import CaptchaProxyError
from src.modules.account.login_flow import LoginFlowCoordinator


def _minimal_account_service() -> object:
    """路由层测试只需要最小账号服务桩。"""

    class AccountService:
        async def login(self, _actor, _attempt):
            raise AssertionError("路由测试不应触发登录")

        async def login_with_credentials(self, _actor, _credentials):
            raise AssertionError("路由测试不应触发登录")

    return AccountService()


def test_build_upstream_url_keeps_query_byte_level() -> None:
    url = captcha_proxy.build_upstream_url(
        "captcha.alicaptcha.com",
        "load",
        "callback=geetest_1&v=1%202%2B3",
    )
    assert url == "https://captcha.alicaptcha.com/load?callback=geetest_1&v=1%202%2B3"


def test_build_upstream_url_without_query() -> None:
    url = captcha_proxy.build_upstream_url("static.alicaptcha.com", "v4/gt4.js", "")
    assert url == "https://static.alicaptcha.com/v4/gt4.js"


@pytest.mark.parametrize(
    "host",
    [
        "evil.alicaptcha.com.attacker.com",
        "alicaptcha.com.evil.com",
        "captcha.alicaptcha.com.evil.com",
        "",
        "example.com",
    ],
)
def test_build_upstream_url_rejects_non_whitelist_host(host: str) -> None:
    assert captcha_proxy.build_upstream_url(host, "load", "a=1") is None


def test_forward_headers_replace_windows_ua_with_android_profile() -> None:
    headers = captcha_proxy.build_forward_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": "session=abc",
            "X-Custom": "x",
        },
        method="GET",
    )
    # 浏览器 UA 绝不透传；固定为与官方 App 一致的 Android 画像。
    assert "Windows" not in headers["User-Agent"]
    assert "Android" in headers["User-Agent"]
    assert headers["sec-ch-ua-platform"] == '"Android"'
    assert headers["sec-ch-ua-mobile"] == "?1"
    assert headers["Accept"] == "application/json"
    assert headers["Accept-Language"] == "zh-CN,zh;q=0.9"
    # Alicom 校验 Referer/Origin，固定为官方 H5 来源。
    assert headers["Referer"] == "https://dnabbs.yingxiong.com/"
    assert headers["Origin"] == "https://dnabbs.yingxiong.com"
    # 其余浏览器头一律丢弃，避免穿帮或泄露。
    assert "Cookie" not in headers
    assert "X-Custom" not in headers
    # GET 不应带 Content-Type。
    assert "Content-Type" not in headers


def test_forward_headers_post_keeps_content_type() -> None:
    headers = captcha_proxy.build_forward_headers(
        {"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_forward_headers_fill_safe_defaults() -> None:
    headers = captcha_proxy.build_forward_headers({}, method="GET")
    assert "Accept" in headers
    assert "Accept-Language" in headers


@pytest.mark.asyncio
async def test_forward_passes_body_method_and_maps_response() -> None:
    captured: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content
        captured["ua"] = request.headers.get("user-agent", "")
        captured["cookie"] = request.headers.get("cookie")
        return httpx.Response(
            201,
            content=b'{"code":200}',
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        result = await captcha_proxy.forward(
            "captchabak.alicaptcha.com",
            "verify",
            "a=1",
            "POST",
            {"Content-Type": "text/plain", "Cookie": "nope=1"},
            b"W5payload",
            client=client,
        )

    assert captured["url"] == "https://captchabak.alicaptcha.com/verify?a=1"
    assert captured["method"] == "POST"
    assert captured["body"] == b"W5payload"
    assert "Android" in str(captured["ua"])
    assert captured["cookie"] is None
    assert result is not None
    assert result.status == 201
    assert result.content_type == "application/json"
    assert result.body == b'{"code":200}'


@pytest.mark.asyncio
async def test_forward_reuses_client_and_rejects_unknown_host_without_network() -> (
    None
):
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("白名单外 host 不应产生网络请求")

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        assert (
            await captcha_proxy.forward(
                "example.com", "load", "", "GET", {}, b"", client=client
            )
            is None
        )


@pytest.mark.asyncio
async def test_forward_network_error_raises_proxy_error() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(CaptchaProxyError):
            await captcha_proxy.forward(
                "captcha.alicaptcha.com", "load", "", "GET", {}, b"", client=client
            )


@pytest.mark.asyncio
async def test_forward_surfaces_upstream_error_status() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden", headers={
            "Content-Type": "text/plain",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        result = await captcha_proxy.forward(
            "captcha.alicaptcha.com", "load", "", "GET", {}, b"", client=client
        )
    assert result is not None
    assert result.status == 403
    assert result.body == b"forbidden"


@pytest.mark.asyncio
async def test_local_server_serves_service_worker_and_rejects_unknown_proxy_host() -> (
    None
):
    """local 登录服务暴露 sw.js 与 alicap 路由；白名单外 host 直接 404。"""

    import aiohttp

    flow = LoginFlowCoordinator(
        _minimal_account_service(),
        LoginSettings(transport="local", port=0),
        account_transport=None,
    )
    await flow.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{flow.public_url}/sw.js") as response:
                assert response.status == 200
                assert "javascript" in response.headers["Content-Type"]
                assert response.headers.get("Cache-Control") == "no-cache"
                assert (
                    "Service-Worker-Allowed" in response.headers
                )
                assert "alicaptcha.com" in await response.text()

            async with session.get(
                f"{flow.public_url}/alicap/example.com/load?a=1"
            ) as response:
                assert response.status == 404
    finally:
        await flow.stop()


@pytest.mark.asyncio
async def test_alicap_route_forwards_arbitrary_subpath_and_query() -> None:
    """alicap handler 把子路径和未解码 query 字节级交给转发层。

    直接调用 handler 而不是走 aiohttp 客户端：客户端会规范化 URL
    （如 %2F → /），无法用于验证服务端是否保持原始字节。
    """

    seen: dict[str, object] = {}

    async def fake_forward(host, path, query, method, headers, body, client):
        del client
        seen.update(host=host, path=path, query=query, method=method, body=body)
        return captcha_proxy.ProxyResult(
            status=200, content_type="text/plain", body=b"ok"
        )

    class RawRequest:
        method = "POST"
        query_string = "c=a%2Fb&d=1"
        headers: ClassVar[dict[str, str]] = {"Content-Type": "text/plain"}

        async def read(self) -> bytes:
            return b"raw-body"

    flow = LoginFlowCoordinator(
        _minimal_account_service(),
        LoginSettings(transport="local", port=0),
        account_transport=None,
    )
    flow._captcha_forward = fake_forward
    response = await flow._captcha_proxy(
        "captcha.alicaptcha.com", "v4/verify", raw_request=RawRequest()
    )
    assert response.status_code == 200
    assert response.body == b"ok"
    assert seen["host"] == "captcha.alicaptcha.com"
    assert seen["path"] == "v4/verify"
    assert seen["query"] == "c=a%2Fb&d=1"
    assert seen["method"] == "POST"
    assert seen["body"] == b"raw-body"


@pytest.mark.asyncio
async def test_login_page_registers_service_worker_and_page_hook() -> None:
    """登录页必须在加载 ct4.js 之前注册 SW 并安装页面内传输 hook。"""

    import aiohttp

    flow = LoginFlowCoordinator(
        _minimal_account_service(),
        LoginSettings(transport="local", port=0),
        account_transport=None,
    )
    await flow.start()
    try:
        from src.modules.account.contracts import AccountActor

        actor = AccountActor(user_id="u1", bot_id="b1", unified_msg_origin="x:y")
        response = await flow.begin(actor)
        login_url = response.text.removeprefix("登录地址：")
        async with aiohttp.ClientSession() as session, session.get(
            login_url
        ) as page_response:
            assert page_response.status == 200
            page = await page_response.text()
        assert "serviceWorker" in page
        assert "/alicap/" in page
        # hook 必须先于验证码 SDK 加载：hook 安装代码出现在 ct4.js 引用之前。
        assert page.index("/alicap/") < page.index("ct4.js")
    finally:
        await flow.stop()
