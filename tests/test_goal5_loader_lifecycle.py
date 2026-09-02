"""Goal 5 Task 04：官方 loader harness 生命周期 Red 契约。

这些测试只依赖 loader 脚本显式提供的 ``LoaderRuntime`` seam；生产路径仍必须由
官方 ``PluginManager.load()`` 驱动，fake manager 仅用于离线验证失败和清理语义。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI_SCRIPT = ROOT / "scripts" / "ci" / "check_astrbot_plugin_load.py"


def _load_module(path: Path, module_name: str) -> ModuleType:
    assert path.is_file(), f"目标脚本不存在：{path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _FakePlugin:
    events: list[str]
    fail_terminate: bool = False
    initialize_error: BaseException | None = None

    async def initialize(self) -> None:
        if self.initialize_error is not None:
            raise self.initialize_error

    async def terminate(self) -> None:
        self.events.append("terminate")
        if self.fail_terminate:
            raise RuntimeError("terminate sentinel")


class _FakeContext:
    def __init__(self, metadata: Any) -> None:
        self.metadata = metadata

    def get_all_stars(self) -> list[Any]:
        return [self.metadata]


class _FakeManager:
    def __init__(
        self,
        context: _FakeContext,
        events: list[str],
        *,
        load_result: tuple[bool, str | None],
        initialize_error: BaseException | None = None,
        failure_record: dict[str, str] | None = None,
    ) -> None:
        self.context = context
        self.events = events
        self.load_result = load_result
        self.failed_plugin_dict = (
            {"astrbot_plugin_dnaby": failure_record}
            if failure_record is not None
            else {}
        )

    async def load(self, *, specified_dir_name: str) -> tuple[bool, str | None]:
        self.events.append(f"load:{specified_dir_name}")
        plugin = self.context.metadata.star_cls
        initialize = getattr(plugin, "initialize", None)
        if callable(initialize):
            self.events.append("initialize")
            result = initialize()
            if asyncio.iscoroutine(result):
                await result
        return self.load_result


def _runtime_factory(
    *,
    loader_module: ModuleType,
    events: list[str],
    load_result: tuple[bool, str | None] = (True, None),
    plugin: Any | None = None,
    initialize_error: BaseException | None = None,
    failure_record: dict[str, str] | None = None,
):
    plugin = plugin or _FakePlugin(events, initialize_error=initialize_error)
    metadata = SimpleNamespace(
        name="astrbot_plugin_dnaby",
        root_dir_name="astrbot_plugin_dnaby",
        version="v0.2.0",
        module_path="data.plugins.astrbot_plugin_dnaby.main",
        module=SimpleNamespace(COMMAND_REGISTRY=[SimpleNamespace(id="demo")]),
        star_cls=plugin,
        star_handler_full_names=("data.plugins.astrbot_plugin_dnaby.main.handle_demo",),
    )
    context = _FakeContext(metadata)
    manager = _FakeManager(
        context,
        events,
        load_result=load_result,
        failure_record=failure_record,
    )

    def factory(*_args: object, **_kwargs: object):
        return loader_module.LoaderRuntime(context=context, plugin_manager=manager)

    return factory


def _seed_plugin_source(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "main.py").write_text("# fake source\n", encoding="utf-8")
    (root / "metadata.yaml").write_text(
        "name: astrbot_plugin_dnaby\n"
        "author: FlanChanXwO\n"
        "desc: fake\n"
        "version: v0.2.0\n"
        "astrbot_version: '>=4.27.1'\n",
        encoding="utf-8",
    )
    (root / "commands.json").write_text(
        '[{"id": "demo"}]\n',
        encoding="utf-8",
    )


def _load_contract_module() -> ModuleType:
    return _load_module(CI_SCRIPT, "goal5_loader_lifecycle_contracts")


@pytest.mark.asyncio
async def test_loader_calls_official_load_and_terminates_after_success(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"

    report = await module.run_loader_check(
        astrbot_source=tmp_path / "astrbot-source",
        astrbot_version="4.27.1",
        plugin_dir=plugin_dir,
        astrbot_root=root,
        plugin_name="astrbot_plugin_dnaby",
        runtime_factory=_runtime_factory(loader_module=module, events=events),
    )

    assert events == ["load:astrbot_plugin_dnaby", "initialize", "terminate"]
    assert report.astrbot_version == "4.27.1"
    assert report.plugin_name == "astrbot_plugin_dnaby"
    assert report.plugin_version == "v0.2.0"
    assert report.load_succeeded is True
    assert report.initialize_succeeded is True
    assert report.terminate_succeeded is True
    assert not root.exists()


@pytest.mark.asyncio
async def test_loader_failure_still_terminates_plugin_and_preserves_phase(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"

    with pytest.raises(module.LoaderCheckError, match="official loader") as caught:
        await module.run_loader_check(
            astrbot_source=tmp_path / "astrbot-source",
            astrbot_version="master",
            plugin_dir=plugin_dir,
            astrbot_root=root,
            plugin_name="astrbot_plugin_dnaby",
            runtime_factory=_runtime_factory(
                loader_module=module,
                events=events,
                load_result=(False, "official loader sentinel"),
            ),
        )

    assert caught.value.phase == "load"
    assert events == ["load:astrbot_plugin_dnaby", "initialize", "terminate"]
    assert not root.exists()


@pytest.mark.asyncio
async def test_official_load_failure_record_preserves_initialize_traceback(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"
    official_traceback = (
        "Traceback (most recent call last):\n"
        "  File \\\"plugin/main.py\\\", line 7, in initialize\\n"
        "    raise RuntimeError(\\\"official initialize sentinel\\\")\\n"
        "RuntimeError: official initialize sentinel\\n"
    )

    with pytest.raises(module.LoaderCheckError, match="official initialize sentinel") as caught:
        await module.run_loader_check(
            astrbot_source=tmp_path / "astrbot-source",
            astrbot_version="4.27.1",
            plugin_dir=plugin_dir,
            astrbot_root=root,
            plugin_name="astrbot_plugin_dnaby",
            runtime_factory=_runtime_factory(
                loader_module=module,
                events=events,
                load_result=(False, "official loader failure summary"),
                failure_record={
                    "error": "official initialize sentinel",
                    "traceback": official_traceback,
                },
            ),
        )

    assert caught.value.phase == "initialize"
    assert "in initialize" in str(caught.value)
    assert events == ["load:astrbot_plugin_dnaby", "initialize", "terminate"]
    assert not root.exists()


@pytest.mark.asyncio
async def test_initialize_failure_keeps_original_error_and_runs_termination_cleanup(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"
    initialize_error = RuntimeError("initialize sentinel")

    with pytest.raises(module.LoaderCheckError, match="initialize sentinel") as caught:
        await module.run_loader_check(
            astrbot_source=tmp_path / "astrbot-source",
            astrbot_version="4.27.1",
            plugin_dir=plugin_dir,
            astrbot_root=root,
            plugin_name="astrbot_plugin_dnaby",
            runtime_factory=_runtime_factory(
                loader_module=module,
                events=events,
                initialize_error=initialize_error,
            ),
        )

    assert caught.value.phase == "initialize"
    assert events == ["load:astrbot_plugin_dnaby", "initialize", "terminate"]
    assert not root.exists()


@pytest.mark.asyncio
async def test_loader_rejects_success_without_registered_plugin(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"
    factory = _runtime_factory(loader_module=module, events=events)
    runtime = factory()
    runtime.context.get_all_stars = lambda: []

    def missing_registration_factory(*_args: object, **_kwargs: object):
        return runtime

    with pytest.raises(module.LoaderCheckError, match="registered|registration") as caught:
        await module.run_loader_check(
            astrbot_source=tmp_path / "astrbot-source",
            astrbot_version="4.27.1",
            plugin_dir=plugin_dir,
            astrbot_root=root,
            plugin_name="astrbot_plugin_dnaby",
            runtime_factory=missing_registration_factory,
        )

    assert caught.value.phase == "registration"
    assert events == ["load:astrbot_plugin_dnaby", "initialize"]
    assert not root.exists()


@pytest.mark.asyncio
async def test_termination_failure_is_a_nonzero_cleanup_phase(
    tmp_path: Path,
) -> None:
    module = _load_contract_module()
    plugin_dir = tmp_path / "plugin"
    _seed_plugin_source(plugin_dir)
    (tmp_path / "astrbot-source").mkdir()
    events: list[str] = []
    root = tmp_path / "astrbot-root"
    plugin = _FakePlugin(events, fail_terminate=True)

    with pytest.raises(module.LoaderCheckError, match="terminate sentinel") as caught:
        await module.run_loader_check(
            astrbot_source=tmp_path / "astrbot-source",
            astrbot_version="4.27.1",
            plugin_dir=plugin_dir,
            astrbot_root=root,
            plugin_name="astrbot_plugin_dnaby",
            runtime_factory=_runtime_factory(
                loader_module=module,
                events=events,
                plugin=plugin,
            ),
        )

    assert caught.value.phase == "terminate"
    assert events == ["load:astrbot_plugin_dnaby", "initialize", "terminate"]
    assert not root.exists()
