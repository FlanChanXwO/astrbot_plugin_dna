"""Goal 2 / Task 16：验证 AstrBot 插件命名空间可以真实导入。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from astrbot.api.web import PluginRequest, bind_request_context
from starlette.datastructures import Headers, QueryParams

from src.entry.admin_web import AdminWebAdapter
from src.modules.admin import AdminApiResponse


def test_plugin_main_imports_from_astrbot_namespace() -> None:
    """AstrBot 的 data.plugins 命名空间不应依赖插件目录成为 cwd。"""

    runtime_root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "data" / "plugins").is_dir()
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", "import data.plugins.astrbot_plugin_dnaby.main"],
        cwd=runtime_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_encoded_alias_role_is_decoded_before_admin_service_call() -> None:
    """插件页桥接层编码中文角色名后，Web 适配器仍应传递规范名称。"""

    class _RawRequest:
        method = "POST"
        url = SimpleNamespace(path="/astrbot_plugin_dnaby/admin/aliases/role")
        headers = Headers({"content-type": "application/json"})
        cookies: ClassVar[dict[str, str]] = {}
        client = SimpleNamespace(host="127.0.0.1")
        query_params = QueryParams()

        async def json(self) -> object:
            return {"alias": "浏览器别名"}

    class _Aliases:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def add_alias(self, role_name: str, alias: str) -> AdminApiResponse:
            self.calls.append((role_name, alias))
            return AdminApiResponse.success({"role_name": role_name, "alias": alias})

    aliases = _Aliases()
    adapter = AdminWebAdapter({"admin_alias_service": aliases})
    request = PluginRequest(_RawRequest(), username="dashboard-admin")

    with bind_request_context(request):
        response = await adapter.add_alias(
            "%E6%B5%8B%E8%AF%95%E8%A7%92%E8%89%B2",
        )

    assert response.status_code == 200
    assert aliases.calls == [("测试角色", "浏览器别名")]
    assert json.loads(response.body)["data"] == {
        "role_name": "测试角色",
        "alias": "浏览器别名",
    }


def test_plugin_page_wraps_petite_vue_else_fragment_in_an_element() -> None:
    """Top-level v-if nodes must have an Element parent when v-else is mounted."""

    page = Path(__file__).parents[1] / "pages" / "dashboard" / "index.html"
    source = page.read_text(encoding="utf-8")

    assert '<div v-else class="page-content">' in source


def test_confirmation_modal_stacks_above_the_page() -> None:
    """确认对话框和编辑模态框都应位于页面内容之上。"""

    stylesheet = Path(__file__).parents[1] / "pages" / "dashboard" / "css" / "dashboard.css"
    source = stylesheet.read_text(encoding="utf-8")

    assert re.search(r"\.overlay\s*\{[^}]*z-index:\s*50;", source, re.DOTALL)
    assert re.search(r"\.sidebar\s*\{[^}]*z-index:\s*20;", source, re.DOTALL)
