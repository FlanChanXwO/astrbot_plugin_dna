"""Goal 5：AstrBot loader 的完整卸载与资源清理契约。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CI_SCRIPT = ROOT / "scripts" / "ci" / "check_astrbot_plugin_lifecycle.py"
PLUGIN_NAME = "astrbot_plugin_dnaby"
FIXTURE_ASTRBOT_VERSION = "fixture-runtime"
FIXTURE_ASTRBOT_SPEC = "fixture-spec"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "goal5_loader_cleanup_contracts", CI_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_plugin_source(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "main.py").write_text("# fake source\n", encoding="utf-8")
    (root / "metadata.yaml").write_text(
        "name: astrbot_plugin_dnaby\n"
        "author: FlanChanXwO\n"
        "desc: fake\n"
        "version: v0.2.0\n"
        f"astrbot_version: {FIXTURE_ASTRBOT_SPEC}\n",
        encoding="utf-8",
    )
    (root / "commands.json").write_text('[{"id": "demo"}]\n', encoding="utf-8")


@dataclass
class _RuntimeState:
    handlers: list[object] = field(default_factory=list)
    tools: list[object] = field(default_factory=list)
    web_apis: list[object] = field(default_factory=list)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)


class _FakePlugin:
    def __init__(
        self, state: _RuntimeState, events: list[str], *, leak_task: bool
    ) -> None:
        self.state = state
        self.events = events
        self.leak_task = leak_task

    async def initialize(self) -> None:
        self.events.append("initialize")

    async def terminate(self) -> None:
        self.events.append("plugin-terminate")
        if self.leak_task:
            return
        for task in tuple(self.state.tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class _FakeContext:
    def __init__(self, metadata: Any) -> None:
        self.metadata = metadata
        self.active = True

    def get_all_stars(self) -> list[Any]:
        return [self.metadata] if self.active else []


class _FakeManager:
    def __init__(
        self,
        context: _FakeContext,
        state: _RuntimeState,
        events: list[str],
        *,
        leak_registry: str | None,
    ) -> None:
        self.context = context
        self.state = state
        self.events = events
        self.leak_registry = leak_registry
        self.failed_plugin_dict: dict[str, object] = {}

    async def load(self, *, specified_dir_name: str) -> tuple[bool, None]:
        self.events.append(f"load:{specified_dir_name}")
        self.state.handlers.append(object())
        self.state.tools.append(object())
        self.state.web_apis.append(object())
        self.state.tasks.append(asyncio.create_task(asyncio.Event().wait()))
        await self.context.metadata.star_cls.initialize()
        return True, None

    async def _terminate_plugin(self, metadata: Any) -> None:
        self.events.append("manager-terminate")
        await metadata.star_cls.terminate()

    async def _unbind_plugin(self, plugin_name: str, plugin_module_path: str) -> None:
        self.events.append(f"unbind:{plugin_name}:{plugin_module_path}")
        if self.leak_registry != "handlers":
            self.state.handlers.clear()
        if self.leak_registry != "tools":
            self.state.tools.clear()
        if self.leak_registry != "web_apis":
            self.state.web_apis.clear()
        self.context.active = False


def _runtime_factory(
    module: ModuleType,
    *,
    events: list[str],
    state: _RuntimeState,
    leak_registry: str | None = None,
    leak_task: bool = False,
):
    plugin = _FakePlugin(state, events, leak_task=leak_task)
    metadata = SimpleNamespace(
        name=PLUGIN_NAME,
        root_dir_name=PLUGIN_NAME,
        version="v0.2.0",
        module_path=f"data.plugins.{PLUGIN_NAME}.main",
        module=SimpleNamespace(COMMAND_REGISTRY=[SimpleNamespace(id="demo")]),
        star_cls=plugin,
        star_handler_full_names=(f"data.plugins.{PLUGIN_NAME}.main.handle_demo",),
    )
    context = _FakeContext(metadata)
    manager = _FakeManager(
        context,
        state,
        events,
        leak_registry=leak_registry,
    )

    def snapshot_state():
        return module.RuntimeSnapshot(
            handlers=tuple(state.handlers),
            tools=tuple(state.tools),
            web_apis=tuple(state.web_apis),
            tasks=tuple(task for task in state.tasks if not task.done()),
        )

    def factory(*_args: object, **_kwargs: object):
        return module.LoaderRuntime(
            context=context,
            plugin_manager=manager,
            snapshot_state=snapshot_state,
        )

    return factory


async def _run(
    module: ModuleType,
    tmp_path: Path,
    *,
    events: list[str],
    state: _RuntimeState,
    leak_registry: str | None = None,
    leak_task: bool = False,
):
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    return await module.run_loader_check(
        astrbot_source=tmp_path / "astrbot-source",
        astrbot_version=FIXTURE_ASTRBOT_VERSION,
        plugin_dir=plugin_dir,
        astrbot_root=tmp_path / "astrbot-root",
        plugin_name=PLUGIN_NAME,
        runtime_factory=_runtime_factory(
            module,
            events=events,
            state=state,
            leak_registry=leak_registry,
            leak_task=leak_task,
        ),
    )


class LoaderCleanupContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_uses_official_terminate_and_unbind_then_verifies_clean_state(
        self,
    ) -> None:
        module = _load_module()
        events: list[str] = []
        state = _RuntimeState()

        with tempfile.TemporaryDirectory() as directory:
            report = await _run(module, Path(directory), events=events, state=state)

        self.assertEqual(
            events,
            [
                f"load:{PLUGIN_NAME}",
                "initialize",
                "manager-terminate",
                "plugin-terminate",
                f"unbind:{PLUGIN_NAME}:data.plugins.{PLUGIN_NAME}.main",
            ],
        )
        self.assertTrue(report.terminate_succeeded)
        self.assertTrue(report.unbind_succeeded)
        self.assertTrue(report.resource_cleanup_succeeded)

    async def test_lifecycle_rejects_runtime_registry_residue(self) -> None:
        for leak_registry in ("handlers", "tools", "web_apis"):
            with self.subTest(leak_registry=leak_registry):
                module = _load_module()
                events: list[str] = []
                state = _RuntimeState()
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(
                        module.LoaderCheckError,
                        leak_registry,
                    ) as caught:
                        await _run(
                            module,
                            Path(directory),
                            events=events,
                            state=state,
                            leak_registry=leak_registry,
                        )
                self.assertEqual(caught.exception.phase, "resource cleanup")

    async def test_lifecycle_rejects_background_task_residue(self) -> None:
        module = _load_module()
        events: list[str] = []
        state = _RuntimeState()

        try:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(module.LoaderCheckError, "tasks") as caught:
                    await _run(
                        module,
                        Path(directory),
                        events=events,
                        state=state,
                        leak_task=True,
                    )
            self.assertEqual(caught.exception.phase, "resource cleanup")
        finally:
            for task in state.tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*state.tasks, return_exceptions=True)

    def test_lifecycle_ci_enables_canonical_agent_tools_key(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "data" / "config" / f"{PLUGIN_NAME}_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"login": {"port": 0}}),
                encoding="utf-8",
            )

            module._enable_ci_agent_tools(root, PLUGIN_NAME)

            payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["ai"]["agent_tools_enabled"])
        self.assertNotIn("agent_tools", payload)


if __name__ == "__main__":
    unittest.main()
