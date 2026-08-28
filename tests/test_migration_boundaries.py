"""迁移边界回归测试。"""

import asyncio
import sys
from pathlib import Path


def test_web_routes_match_astrbot_registration_contract():
    """Web 路由元组必须与 ``Context.register_web_api`` 的调用顺序一致。"""
    from src.modules.account.login_router import get_routes

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
    from src.modules.account import login_router

    assert callable(login_router.get_qrcode_base64)


def test_login_router_uses_runtime_timeout_support():
    """登录轮询使用运行时自带的异步超时能力，不依赖额外包。"""
    from src.modules.account import login_router

    assert callable(login_router.asyncio.timeout)


def test_login_session_token_is_not_derived_from_user_id():
    """登录 URL 的会话标识不能被知道 user_id 的外部请求者预测。"""
    import hashlib

    from src.modules.account.login_helps import get_token

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

    from src.modules.account import transport

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


def _load_worktree_main_module():
    import importlib.util
    import types

    for pkg in ["data", "data.plugins", "data.plugins.astrbot_plugin_dnaby"]:
        if pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__ = []
            sys.modules[pkg] = mod

    worktree_root = Path(__file__).resolve().parent.parent
    sys.modules["data.plugins.astrbot_plugin_dnaby"].__path__ = [str(worktree_root)]

    main_path = worktree_root / "main.py"
    spec = importlib.util.spec_from_file_location(
        "data.plugins.astrbot_plugin_dnaby.main",
        main_path,
        submodule_search_locations=[str(worktree_root)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "data.plugins.astrbot_plugin_dnaby"
    sys.modules["data.plugins.astrbot_plugin_dnaby.main"] = module
    spec.loader.exec_module(module)
    return module



def test_plugin_entrypoint_imports_in_astrbot_namespace():
    """AstrBot 的动态模块命名空间必须能加载包内业务模块。"""
    module = _load_worktree_main_module()
    assert module.DnabyPlugin.__name__ == "DnabyPlugin"


def test_dynamic_plugin_builds_empty_runtime_from_package_namespace():
    """动态命名空间下的入口必须能组装 v0.1 空 runtime。"""
    import types

    module = _load_worktree_main_module()

    registered = []
    context = types.SimpleNamespace(
        register_web_api=lambda *args: registered.append(args),
    )

    runtime = module.build_runtime(context, {})

    async def lifecycle() -> None:
        await runtime.initialize()
        await runtime.terminate()

    asyncio.run(lifecycle())

    assert registered == []


def test_package_namespace_import_does_not_depend_on_top_level_src():
    """包名加载必须在没有顶层 ``src`` 兼容模块的干净进程中成立。"""
    import subprocess

    script = r'''
import importlib.util
import sys
import types
from pathlib import Path

root = Path(sys.argv[1])
for pkg in ["data", "data.plugins", "data.plugins.astrbot_plugin_dnaby"]:
    module = types.ModuleType(pkg)
    module.__path__ = []
    sys.modules[pkg] = module
sys.modules["data.plugins.astrbot_plugin_dnaby"].__path__ = [str(root)]
spec = importlib.util.spec_from_file_location(
    "data.plugins.astrbot_plugin_dnaby.main",
    root / "main.py",
    submodule_search_locations=[str(root)],
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert len(module.COMMAND_REGISTRY) == 60
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parent.parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_mh_list_order_is_stable():
    """动态密函命令的角色顺序必须跨进程稳定，避免清单漂移。"""
    from src.utils.api.mh_map import get_mh_list

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
