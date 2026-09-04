"""Goal 5：插件卸载时的 AstrBot Web API 清理契约。"""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WebRegistrar = import_module("src.entry.web").WebRegistrar


class _Context:
    def __init__(self) -> None:
        self.registered_web_apis: list[tuple[object, ...]] = []


async def _owned_handler() -> None:
    return None


async def _other_handler() -> None:
    return None


class WebLifecycleTests(unittest.TestCase):
    def test_unregister_plugin_routes_removes_only_plugin_namespace(self) -> None:
        context = _Context()
        context.registered_web_apis.extend(
            [
                (
                    "/astrbot_plugin_dnaby/admin/bootstrap",
                    _owned_handler,
                    ["GET"],
                    "dnaby",
                ),
                (
                    "/astrbot_plugin_dnaby/admin/accounts",
                    _owned_handler,
                    ["GET"],
                    "dnaby",
                ),
                ("/other_plugin/ping", _other_handler, ["GET"], "other"),
            ]
        )

        WebRegistrar.unregister_plugin_routes(
            context,  # type: ignore[arg-type]
            "astrbot_plugin_dnaby",
        )

        self.assertEqual(
            context.registered_web_apis,
            [("/other_plugin/ping", _other_handler, ["GET"], "other")],
        )


if __name__ == "__main__":
    unittest.main()
