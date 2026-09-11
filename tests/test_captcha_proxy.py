"""验证码反代：host 白名单、Android 画像注入、原始字节透传与跳转安全。

248 的判别发生在发给 ``*.alicaptcha.com`` 请求的 HTTP ``User-Agent``
平台标识；反代必须把 UA/UA-CH 固定为实测过的 Android 画像，并把反代入口绑定
到仍然有效的登录会话。具体证据见 DNA-analysis ``docs/login-248/10``。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import yarl

from src.infrastructure.config.settings import LoginSettings
from src.infrastructure.http import captcha_proxy
from src.infrastructure.http.captcha_proxy import CaptchaProxyError
from src.modules.account.contracts import AccountActor
from src.modules.account.login_flow import LoginFlowCoordinator

ROOT = Path(__file__).resolve().parents[1]
PROXY_PREFIX = "/astrbot_plugin_dna/alicap/A1/"


def _minimal_account_service() -> object:
    """路由层测试只需要最小账号服务桩。"""

    class AccountService:
        async def login(self, _actor, _attempt):
            raise AssertionError("路由测试不应触发登录")

        async def login_with_credentials(self, _actor, _credentials):
            raise AssertionError("路由测试不应触发登录")

    return AccountService()


@asynccontextmanager
async def _started_flow(**settings: Any):
    flow = LoginFlowCoordinator(
        _minimal_account_service(),
        LoginSettings(transport="local", port=0, **settings),
        account_transport=None,
    )
    await flow.start()
    try:
        yield flow
    finally:
        await flow.stop()


async def _open_session(flow: LoginFlowCoordinator) -> str:
    """开启一个真实登录会话并返回它的 auth。"""

    await flow.begin(AccountActor(user_id="u1", bot_id="b1", unified_msg_origin="x:y"))
    return next(iter(flow._sessions.values())).auth


# --------------------------------------------------------------------------
# host 白名单与上游地址拼接
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Android 画像注入
# --------------------------------------------------------------------------


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


@pytest.mark.parametrize(
    ("method", "incoming", "expected"),
    [
        ("POST", {"Content-Type": "text/plain"}, "text/plain"),
        ("POST", {}, "application/x-www-form-urlencoded"),
        ("GET", {"Content-Type": "text/plain"}, None),
    ],
)
def test_forward_headers_keep_content_type_only_for_body_methods(
    method: str,
    incoming: dict[str, str],
    expected: str | None,
) -> None:
    headers = captcha_proxy.build_forward_headers(incoming, method=method)
    assert headers.get("Content-Type") == expected


def test_forward_headers_fill_safe_defaults() -> None:
    headers = captcha_proxy.build_forward_headers({}, method="GET")
    assert "Accept" in headers
    assert "Accept-Language" in headers


# --------------------------------------------------------------------------
# 出站客户端契约
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_http_client_keeps_connect_budget_and_no_read_deadline() -> None:
    """沿用项目既有建连约定，但不给上游读取设置人为截止时间。"""

    async with captcha_proxy.new_http_client() as client:
        assert client.follow_redirects is False
        assert client.timeout.connect == captcha_proxy.PROXY_CONNECT_TIMEOUT_S
        assert client.timeout.read is None


@pytest.mark.asyncio
async def test_client_does_not_follow_upstream_redirects() -> None:
    """跟随跳转会让上游把请求带出白名单，必须由反代自己校验并重写。"""

    seen: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "/b"})
        return httpx.Response(200, content=b"ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), follow_redirects=False
    ) as client:
        result = await captcha_proxy.forward(
            "captcha.alicaptcha.com",
            "a",
            "",
            "GET",
            {},
            b"",
            client=client,
            proxy_prefix=PROXY_PREFIX,
        )
    assert result is not None
    assert seen == ["/a"]


# --------------------------------------------------------------------------
# 响应映射
# --------------------------------------------------------------------------


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
            proxy_prefix=PROXY_PREFIX,
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
    assert result.location is None


@pytest.mark.asyncio
async def test_forward_rejects_unknown_host_without_network() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("白名单外 host 不应产生网络请求")

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        assert (
            await captcha_proxy.forward(
                "example.com",
                "load",
                "",
                "GET",
                {},
                b"",
                client=client,
                proxy_prefix=PROXY_PREFIX,
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
                "captcha.alicaptcha.com",
                "load",
                "",
                "GET",
                {},
                b"",
                client=client,
                proxy_prefix=PROXY_PREFIX,
            )


@pytest.mark.asyncio
async def test_forward_surfaces_upstream_error_status() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            content=b"forbidden",
            headers={"Content-Type": "text/plain"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        result = await captcha_proxy.forward(
            "captcha.alicaptcha.com",
            "load",
            "",
            "GET",
            {},
            b"",
            client=client,
            proxy_prefix=PROXY_PREFIX,
        )
    assert result is not None
    assert result.status == 403
    assert result.body == b"forbidden"


# --------------------------------------------------------------------------
# 跳转安全
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected_path"),
    [
        (
            "https://captchabak.alicaptcha.com/b%2Fc?z=1%2F2&v=%23",
            "/astrbot_plugin_dna/alicap/A1/captchabak.alicaptcha.com/b%2Fc?z=1%2F2&v=%23",
        ),
        ("/c?q=%23", "/astrbot_plugin_dna/alicap/A1/captcha.alicaptcha.com/c?q=%23"),
        (
            "//static.alicaptcha.com/f%2Fg",
            "/astrbot_plugin_dna/alicap/A1/static.alicaptcha.com/f%2Fg",
        ),
        (
            "https://captcha.alicaptcha.com:443/b%2Fc",
            "/astrbot_plugin_dna/alicap/A1/captcha.alicaptcha.com/b%2Fc",
        ),
        (
            "https://captcha.alicaptcha.com",
            "/astrbot_plugin_dna/alicap/A1/captcha.alicaptcha.com/",
        ),
    ],
)
def test_rewrite_redirect_keeps_whitelist_encoding(
    location: str, expected_path: str
) -> None:
    rewritten = captcha_proxy.rewrite_redirect(
        location,
        base=httpx.URL("https://captcha.alicaptcha.com/v4/verify?a=1"),
        proxy_prefix=PROXY_PREFIX,
    )
    assert rewritten == expected_path


@pytest.mark.parametrize(
    "location",
    [
        "",
        "https://evil.example.com/x",
        "http://captcha.alicaptcha.com/insecure",
        "https://captcha.alicaptcha.com:8443/other-port",
        "https://notalicaptcha.com/x",
        "https://alicaptcha.com.evil.com/x",
        "javascript:alert(1)",
        "mailto:captcha@alicaptcha.com",
    ],
)
def test_rewrite_redirect_rejects_non_whitelist_target(location: str) -> None:
    assert (
        captcha_proxy.rewrite_redirect(
            location,
            base=httpx.URL("https://captcha.alicaptcha.com/v4/verify?a=1"),
            proxy_prefix=PROXY_PREFIX,
        )
        is None
    )


@pytest.mark.asyncio
async def test_forward_rewrites_whitelist_redirect_and_drops_foreign_one() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ok":
            return httpx.Response(
                302,
                headers={"Location": "https://captchabak.alicaptcha.com/next?n=%23"},
            )
        return httpx.Response(
            301, headers={"Location": "https://evil.example.com/steal"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        allowed = await captcha_proxy.forward(
            "captcha.alicaptcha.com",
            "ok",
            "",
            "GET",
            {},
            b"",
            client=client,
            proxy_prefix=PROXY_PREFIX,
        )
        foreign = await captcha_proxy.forward(
            "captcha.alicaptcha.com",
            "foreign",
            "",
            "GET",
            {},
            b"",
            client=client,
            proxy_prefix=PROXY_PREFIX,
        )

    assert allowed is not None
    assert allowed.status == 302
    assert (
        allowed.location
        == "/astrbot_plugin_dna/alicap/A1/captchabak.alicaptcha.com/next?n=%23"
    )
    assert foreign is not None
    assert foreign.status == 301
    assert foreign.location is None


# --------------------------------------------------------------------------
# 路由层：会话绑定与原始字节透传
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anonymous_alicap_request_is_rejected_without_upstream_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有有效登录会话时不得创建出站客户端，也不得上游请求。"""

    def forbidden_client() -> httpx.AsyncClient:
        raise AssertionError("匿名请求不应创建上游客户端")

    async def forbidden_forward(*_args, **_kwargs):
        raise AssertionError("匿名请求不应触发转发")

    monkeypatch.setattr(captcha_proxy, "new_http_client", forbidden_client)
    async with _started_flow() as flow:
        flow._captcha_forward = forbidden_forward
        import aiohttp

        async with aiohttp.ClientSession() as session:
            for url in (
                f"{flow.public_url}/alicap/nosuchsession/captcha.alicaptcha.com/load?a=1",
                f"{flow.public_url}/alicap/nosuchsession/static.alicaptcha.com/v4/gt4.js",
            ):
                async with session.get(url) as response:
                    assert response.status == 404


@pytest.mark.asyncio
async def test_active_session_can_use_alicap_proxy() -> None:
    """有效登录会话仍然可以正常转发。"""

    seen: dict[str, object] = {}

    async def fake_forward(host, path, query, method, headers, body, **kwargs):
        seen.update(
            host=host,
            path=path,
            query=query,
            method=method,
            body=body,
            proxy_prefix=kwargs.get("proxy_prefix"),
        )
        return captcha_proxy.ProxyResult(
            status=200, content_type="text/plain", body=b"ok"
        )

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        flow._captcha_forward = fake_forward
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{flow.public_url}/alicap/{auth}/captcha.alicaptcha.com/load?a=1"
            ) as response:
                assert response.status == 200
                assert await response.text() == "ok"
    assert seen["host"] == "captcha.alicaptcha.com"
    assert seen["path"] == "load"
    assert seen["query"] == "a=1"
    assert seen["proxy_prefix"] == f"/astrbot_plugin_dna/alicap/{auth}/"


@pytest.mark.asyncio
async def test_alicap_route_round_trips_raw_path_and_query() -> None:
    """经过真实 aiohttp 路由时，子路径与 query 必须字节级透传。

    ``aiohttp`` 的 ``query_string`` 会把 ``%23`` 解码成 ``#``，把 ``+`` 解码成
    空格；重新拼回 URL 后会截断或改变上游参数，因此只能取原始请求行。
    """

    captured: dict[str, object] = {}

    async def fake_forward(host, path, query, method, headers, body, **_kwargs):
        captured.update(path=path, query=query, method=method, body=body)
        return captcha_proxy.ProxyResult(
            status=200, content_type="text/plain", body=b"ok"
        )

    sub_path = "v4/a%2Fb/c%23d/e%252Ff"
    raw_query = "x=%23&e=a+b&p=%25&u=%E4%B8%AD&d=a%252Fb&s=%20&q=%2F&r=%2B"

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        flow._captcha_forward = fake_forward
        target = (
            f"{flow.public_url}/alicap/{auth}"
            f"/captcha.alicaptcha.com/{sub_path}?{raw_query}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(yarl.URL(target, encoded=True)) as response:
                assert response.status == 200

    assert captured["path"] == sub_path
    assert captured["query"] == raw_query
    assert captured["method"] == "GET"


@pytest.mark.asyncio
async def test_alicap_route_preserves_raw_bytes_on_real_outbound_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：经 aiohttp 路由后，上游 httpx 请求行保持原始百分号编码。"""

    seen: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path
        return httpx.Response(200, content=b"ok")

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(upstream), follow_redirects=False
        )

    sub_path = "v4/a%2Fb/c%23d/e%252Ff"
    raw_query = "x=%23&e=a+b&p=%25&u=%E4%B8%AD&d=a%252Fb&s=%20&q=%2F&r=%2B"

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        monkeypatch.setattr(captcha_proxy, "new_http_client", client_factory)
        target = (
            f"{flow.public_url}/alicap/{auth}"
            f"/captcha.alicaptcha.com/{sub_path}?{raw_query}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(yarl.URL(target, encoded=True)) as response:
                assert response.status == 200
                assert await response.text() == "ok"

    assert seen["raw_path"] == (f"/{sub_path}?{raw_query}".encode("ascii"))


@pytest.mark.asyncio
async def test_alicap_redirect_is_rewritten_into_same_origin_proxy() -> None:
    """上游白名单内跳转必须重写回本地同源反代地址并保留 Location。"""

    async def fake_forward(host, path, query, method, headers, body, **_kwargs):
        del host, path, query, method, headers, body
        return captcha_proxy.ProxyResult(
            status=302,
            content_type="text/plain",
            body=b"",
            location="/astrbot_plugin_dna/alicap/A1/static.alicaptcha.com/f%2Fg",
        )

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        flow._captcha_forward = fake_forward
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{flow.public_url}/alicap/{auth}/captcha.alicaptcha.com/load",
                allow_redirects=False,
            ) as response:
                assert response.status == 302
                assert response.headers["Location"] == (
                    "/astrbot_plugin_dna/alicap/A1/static.alicaptcha.com/f%2Fg"
                )


@pytest.mark.asyncio
async def test_alicap_foreign_redirect_is_refused() -> None:
    """非白名单跳转必须明确拒绝，不能下发一个没有目标的 3xx。"""

    async def fake_forward(host, path, query, method, headers, body, **_kwargs):
        del host, path, query, method, headers, body
        return captcha_proxy.ProxyResult(
            status=302, content_type="text/plain", body=b"", location=None
        )

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        flow._captcha_forward = fake_forward
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{flow.public_url}/alicap/{auth}/captcha.alicaptcha.com/load",
                allow_redirects=False,
            ) as response:
                assert response.status == 502


# --------------------------------------------------------------------------
# 静态资源与页面 hook
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_server_serves_service_worker() -> None:
    """local 登录服务暴露禁缓存的验证码 Service Worker。"""

    import aiohttp

    async with _started_flow() as flow:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{flow.public_url}/sw.js") as response:
                assert response.status == 200
                assert "javascript" in response.headers["Content-Type"]
                assert response.headers.get("Cache-Control") == "no-cache"
                assert "Service-Worker-Allowed" in response.headers
                script = await response.text()
        assert "alicaptcha.com" in script
        # Service Worker 必须从受控登录页 URL 解析当前会话 auth，再写入反代地址。
        assert "clients.get" in script
        assert "/alicap/" in script


@pytest.mark.asyncio
async def test_login_page_installs_hook_before_captcha_sdk_and_uses_explicit_hosts() -> (
    None
):
    """登录页必须在加载 ct4.js 之前安装传输 hook，并复用服务端白名单。"""

    import aiohttp

    async with _started_flow() as flow:
        auth = await _open_session(flow)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{flow.public_url}/dna/i/{auth}") as page_response:
                assert page_response.status == 200
                page = await page_response.text()

    assert "serviceWorker" in page
    assert "ALICAP_HOSTS" in page
    # 浏览器侧不能再用宽泛后缀匹配（notalicaptcha.com 会被误伤）。
    assert "endsWith('alicaptcha.com')" not in page
    # hook 安装代码必须先于验证码 SDK 的实际加载语句。
    assert page.index("window.fetch = function") < page.index(
        "script.src = 'https://dnabbs.yingxiong.com/lib/ct4.js'"
    )
    # 反代地址必须携带当前会话 auth。
    assert "sessionAuth" in page
    assert "ALICAP_PROXY_PREFIX = serverUrl + '/alicap/' + sessionAuth + '/'" in page


def _declared_hosts(source: str) -> set[str]:
    """从浏览器侧源码中取出显式声明的 alicaptcha 主机名。"""

    return set(re.findall(r"'([a-z0-9.-]+alicaptcha\.com)'", source))


def test_browser_host_lists_match_server_whitelist() -> None:
    """浏览器侧白名单必须与服务端 ``UPSTREAM_HOSTS`` 保持同步。"""

    expected = set(captcha_proxy.UPSTREAM_HOSTS)
    assert (
        _declared_hosts((ROOT / "src/templates/sw.js").read_text(encoding="utf-8"))
        == expected
    )
    assert (
        _declared_hosts(
            (ROOT / "src/templates/index.html.j2").read_text(encoding="utf-8")
        )
        == expected
    )


_SW_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const SOURCE = fs.readFileSync(process.argv[2], 'utf8');
const SPEC = JSON.parse(process.argv[3]);

const calls = [];
const handlers = {};
const self = {
  location: { origin: 'https://bot.example.com' },
  addEventListener: (name, fn) => { handlers[name] = fn; },
  skipWaiting: () => {},
  clients: {
    claim: async () => {},
    get: async (id) => (id && SPEC.clientUrl ? { url: SPEC.clientUrl } : undefined),
  },
};
const sandbox = {
  self,
  URL,
  Response: class {
    constructor(body, init) { this.body = body; this.status = (init || {}).status; }
  },
  fetch: async (url, init) => {
    calls.push({ url, method: (init || {}).method });
    return { ok: true };
  },
  console,
};
vm.runInNewContext(SOURCE, sandbox);

async function run() {
  const results = [];
  for (const request of SPEC.requests) {
    const event = {
      clientId: SPEC.clientId,
      request: {
        url: request.url,
        method: request.method || 'GET',
        headers: { get: () => null },
        arrayBuffer: async () => new ArrayBuffer(0),
      },
    };
    let outcome = 'not-intercepted';
    let status = null;
    event.respondWith = (promise) => { outcome = 'intercepted'; event._promise = promise; };
    handlers.fetch(event);
    if (event._promise) {
      const response = await event._promise;
      status = response.status === undefined ? null : response.status;
    }
    results.push({ outcome, status });
  }
  process.stdout.write(JSON.stringify({ calls, results }));
}
run();
"""


def _run_service_worker(tmp_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    harness = tmp_path / "harness.js"
    harness.write_text(_SW_HARNESS, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(harness), str(ROOT / "src/templates/sw.js"), json.dumps(spec)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="需要 node 执行 Service Worker 逻辑；环境没有 node 时跳过",
)
def test_service_worker_enforces_session_and_whitelist(tmp_path: Path) -> None:
    """实际执行 sw.js：非白名单不改写，无会话不转发，有会话才带 auth 转发。"""

    spec = {
        "clientId": "client-1",
        "clientUrl": "https://bot.example.com/astrbot_plugin_dna/dna/i/AUTH123",
        "requests": [
            {"url": "https://notalicaptcha.com/v4/a.js"},
            {"url": "https://captcha.alicaptcha.com/v4/a.js"},
        ],
    }
    payload = _run_service_worker(tmp_path, spec)

    # 后缀相似的域名不应被 Service Worker 接管，否则会误伤无关站点。
    assert payload["results"][0] == {"outcome": "not-intercepted", "status": None}
    assert payload["results"][1]["outcome"] == "intercepted"
    assert payload["results"][1]["status"] is None
    assert payload["calls"] == [
        {
            "url": (
                "https://bot.example.com/astrbot_plugin_dna/alicap/AUTH123"
                "/captcha.alicaptcha.com/v4/a.js"
            ),
            "method": "GET",
        }
    ]

    # 无法确认登录会话时必须拒绝，而不是变成匿名中继。
    anonymous = dict(spec, clientId="", clientUrl="")
    payload = _run_service_worker(tmp_path, anonymous)
    assert payload["calls"] == []
    assert payload["results"][1] == {"outcome": "intercepted", "status": 403}
