"""迁移边界回归测试。"""

import asyncio
import importlib
import sys
from pathlib import Path


def test_update_log_git_lookup_is_lazy(monkeypatch):
    """导入更新记录模块不应执行 git 命令，首次使用时才读取日志。"""
    from dnaby.dna_update import draw_update_log

    calls = []
    monkeypatch.setattr(
        draw_update_log,
        "_get_git_logs",
        lambda: calls.append("git-log") or ["✨ test"],
    )
    monkeypatch.setattr(draw_update_log, "_CACHED_LOGS", None)

    assert draw_update_log._get_cached_logs() == ["✨ test"]
    assert draw_update_log._get_cached_logs() == ["✨ test"]
    assert calls == ["git-log"]


def test_web_routes_match_astrbot_registration_contract():
    """Web 路由元组必须与 ``Context.register_web_api`` 的调用顺序一致。"""
    from dnaby.dna_user.login_router import get_routes

    routes = get_routes()
    assert routes
    for route, handler, methods, description in routes:
        assert route.startswith("/astrbot_plugin_dnaby/")
        assert callable(handler)
        assert methods
        assert all(method in {"GET", "POST"} for method in methods)
        assert isinstance(description, str)


def test_login_router_exports_qrcode_helper():
    """登录路由调用的二维码工具必须在模块中显式导入。"""
    from dnaby.dna_user import login_router

    assert callable(login_router.get_qrcode_base64)


def test_login_router_uses_runtime_timeout_support():
    """登录轮询使用运行时自带的异步超时能力，不依赖额外包。"""
    from dnaby.dna_user import login_router

    assert callable(login_router.asyncio.timeout)


def test_login_session_token_is_not_derived_from_user_id():
    """登录 URL 的会话标识不能被知道 user_id 的外部请求者预测。"""
    import hashlib

    from dnaby.dna_user.login_helps import get_token

    token = get_token("user-1")
    assert len(token) == 64
    assert token != hashlib.sha256(b"user-1").hexdigest()[:8]
    assert get_token("user-1") == token
    assert get_token("user-2") != token


def test_http_poll_surfaces_network_failure(monkeypatch):
    """外置轮询连续网络失败时必须显露 TransportError，而不是伪装成超时。"""
    import asyncio

    import httpx
    import pytest

    from dnaby.dna_user import transport

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **kwargs: FailingClient())
    monkeypatch.setattr(transport, "LOGIN_TTL_S", 1)
    monkeypatch.setattr(transport, "POLL_INTERVAL_S", 1)
    monkeypatch.setattr(transport.asyncio, "sleep", no_sleep)

    with pytest.raises(transport.TransportError, match="网络错误"):
        asyncio.run(transport.HttpPollTransport("https://example.test").listen("auth"))


def test_plugin_entrypoint_imports_as_top_level_module():
    """AstrBot 从插件根目录加载 ``main`` 时，入口必须可直接导入。"""
    import importlib

    module = importlib.import_module("main")
    assert module.DnabyPlugin.__name__ == "DnabyPlugin"


def test_plugin_entrypoint_imports_in_astrbot_namespace():
    """AstrBot 的动态模块命名空间必须能加载包内业务模块。"""
    runtime_root = Path(__file__).resolve().parents[4]
    root_text = str(runtime_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    module = importlib.import_module("data.plugins.astrbot_plugin_dnaby.main")
    assert module.DnabyPlugin.__name__ == "DnabyPlugin"


def test_dynamic_plugin_builds_empty_runtime_from_package_namespace():
    """动态命名空间下的入口必须能组装 v0.1 空 runtime。"""
    import types

    module = importlib.import_module("data.plugins.astrbot_plugin_dnaby.main")
    registered = []
    context = types.SimpleNamespace(
        register_web_api=lambda *args: registered.append(args),
    )

    runtime = module.build_runtime(context, {})
    asyncio.run(runtime.initialize())

    assert registered == []


def test_mh_list_order_is_stable():
    """动态密函命令的角色顺序必须跨进程稳定，避免清单漂移。"""
    from dnaby.utils.api.mh_map import get_mh_list

    assert get_mh_list() == [
        "扼守",
        "拆解",
        "勘探",
        "追缉",
        "探险",
        "调停",
        "避险",
        "迁移",
        "驱逐",
        "护送",
        "驱离",
    ]
