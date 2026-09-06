"""验证 dnaby 在官方 AstrBot 中的完整加载/卸载生命周期。

该脚本复用现有 loader harness 的 staging、配置和错误脱敏能力，在真实
``PluginManager.load()`` 成功后继续走 AstrBot 自己的 ``_terminate_plugin()`` 与
``_unbind_plugin()``。卸载返回后会比较运行时快照，任何新增 handler、LLM tool、
Web API 或 asyncio 后台任务仍然存活都会让 CI 失败。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

_LEGACY_PATH = Path(__file__).with_name("check_astrbot_plugin_load.py")


def _load_legacy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "dnaby_plugin_load_harness", _LEGACY_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载现有 loader harness: {_LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_legacy = _load_legacy_module()
LoaderCheckError = _legacy.LoaderCheckError
select_latest_stable_version = _legacy.select_latest_stable_version
_CATCHABLE_ERRORS = (Exception, asyncio.CancelledError)


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """一次运行时快照；对象身份用于区分本轮 lifecycle 新增的资源。"""

    handlers: tuple[object, ...] = ()
    tools: tuple[object, ...] = ()
    web_apis: tuple[object, ...] = ()
    tasks: tuple[asyncio.Task[Any], ...] = ()


@dataclass(slots=True)
class LoaderRuntime:
    """官方 Context/PluginManager、运行时快照和 harness 清理回调。"""

    context: Any
    plugin_manager: Any
    loaded_plugin: Any | None = None
    cleanup_callbacks: tuple[Callable[[], object], ...] = ()
    snapshot_state: Callable[[], RuntimeSnapshot] | None = None


@dataclass(frozen=True, slots=True)
class LoaderReport:
    """一次 lifecycle 检查的可审计结果。"""

    astrbot_version: str
    plugin_name: str
    plugin_version: str
    load_succeeded: bool
    initialize_succeeded: bool
    terminate_succeeded: bool
    unbind_succeeded: bool
    resource_cleanup_succeeded: bool
    command_count: int
    handler_count: int
    registered_handler_count: int
    registered_tool_count: int
    registered_web_api_count: int
    background_task_count: int


def _enable_ci_agent_tools(astrbot_root: Path, plugin_name: str) -> None:
    """只在临时 CI 配置中启用 Agent Tools，以真实覆盖工具注册和解绑。"""

    config_path = astrbot_root / "data" / "config" / f"{plugin_name}_config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    ai = payload.setdefault("ai", {})
    if not isinstance(ai, dict):
        raise TypeError("CI 插件配置中的 ai 必须是对象")
    ai["agent_tools_enabled"] = True
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_official_runtime(
    astrbot_source: Path,
    astrbot_version: str,
    astrbot_root: Path,
    plugin_name: str,
) -> LoaderRuntime:
    legacy_runtime = _legacy._build_official_runtime(
        astrbot_source,
        astrbot_version,
        astrbot_root,
        plugin_name,
    )

    # loader harness 默认不需要 ProviderManager；生命周期检查需要让 dnaby 的
    # Agent Tools 真正注册到 AstrBot 使用的同一份全局 tool registry。
    from astrbot.core.provider.register import llm_tools
    from astrbot.core.star.star_handler import star_handlers_registry

    provider_manager = getattr(legacy_runtime.context, "provider_manager", None)
    if provider_manager is None:
        legacy_runtime.context.provider_manager = SimpleNamespace(llm_tools=llm_tools)
    elif getattr(provider_manager, "llm_tools", None) is None:
        provider_manager.llm_tools = llm_tools

    _enable_ci_agent_tools(astrbot_root, plugin_name)

    def snapshot_state() -> RuntimeSnapshot:
        web_apis = tuple(getattr(legacy_runtime.context, "registered_web_apis", ()))
        pending_tasks = tuple(task for task in asyncio.all_tasks() if not task.done())
        return RuntimeSnapshot(
            handlers=tuple(star_handlers_registry),
            tools=tuple(llm_tools.func_list),
            web_apis=web_apis,
            tasks=pending_tasks,
        )

    return LoaderRuntime(
        context=legacy_runtime.context,
        plugin_manager=legacy_runtime.plugin_manager,
        loaded_plugin=legacy_runtime.loaded_plugin,
        cleanup_callbacks=legacy_runtime.cleanup_callbacks,
        snapshot_state=snapshot_state,
    )


def _added(before: tuple[object, ...], after: tuple[object, ...]) -> tuple[object, ...]:
    before_ids = {id(item) for item in before}
    return tuple(item for item in after if id(item) not in before_ids)


def _delta(before: RuntimeSnapshot, after: RuntimeSnapshot) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        handlers=_added(before.handlers, after.handlers),
        tools=_added(before.tools, after.tools),
        web_apis=_added(before.web_apis, after.web_apis),
        tasks=tuple(
            task
            for task in _added(before.tasks, after.tasks)
            if isinstance(task, asyncio.Task) and not task.done()
        ),
    )


def _describe_handler(handler: object) -> str:
    for attribute in ("handler_name", "full_name", "name"):
        value = getattr(handler, attribute, None)
        if isinstance(value, str) and value:
            return value
    return type(handler).__name__


def _describe_tool(tool: object) -> str:
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) and name else type(tool).__name__


def _describe_web_api(api: object) -> str:
    if isinstance(api, tuple) and api:
        route = api[0]
        methods = api[2] if len(api) > 2 else None
        return f"{route!s} {methods!s}"
    return type(api).__name__


def _describe_task(task: asyncio.Task[Any]) -> str:
    name = task.get_name()
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    if code is not None:
        return f"{name}: {code.co_qualname} ({code.co_filename}:{code.co_firstlineno})"
    return f"{name}: {coro!r}"


def _format_items(items: tuple[object, ...], formatter: Callable[[object], str]) -> str:
    return ", ".join(formatter(item) for item in items)


def _assert_registration_is_observable(added: RuntimeSnapshot) -> None:
    """防止 lifecycle 检查在没有实际覆盖注册动作时假绿。"""

    missing: list[str] = []
    if not added.handlers:
        missing.append("handlers")
    if not added.tools:
        missing.append("tools")
    if not added.web_apis:
        missing.append("web_apis")
    if missing:
        raise LoaderCheckError(
            "registration",
            "lifecycle 没有观察到预期的运行时注册: " + ", ".join(missing),
        )


def _assert_no_runtime_residue(
    baseline: RuntimeSnapshot, final: RuntimeSnapshot
) -> None:
    residue = _delta(baseline, final)
    details: list[str] = []
    if residue.handlers:
        details.append("handlers=" + _format_items(residue.handlers, _describe_handler))
    if residue.tools:
        details.append("tools=" + _format_items(residue.tools, _describe_tool))
    if residue.web_apis:
        details.append("web_apis=" + _format_items(residue.web_apis, _describe_web_api))
    if residue.tasks:
        details.append(
            "tasks=" + ", ".join(_describe_task(task) for task in residue.tasks)
        )
    if details:
        raise LoaderCheckError(
            "resource cleanup",
            "插件卸载后仍存在本轮 lifecycle 新增的运行时资源: " + "; ".join(details),
        )


async def run_loader_check(
    *,
    astrbot_source: str | Path,
    astrbot_version: str,
    plugin_dir: str | Path,
    astrbot_root: str | Path,
    plugin_name: str,
    runtime_factory: Callable[..., LoaderRuntime | Awaitable[LoaderRuntime]]
    | None = None,
) -> LoaderReport:
    """执行 load → official terminate/unbind → residue check。"""

    source = Path(astrbot_source).expanduser().resolve()
    plugin = Path(plugin_dir).expanduser().resolve()
    root = Path(astrbot_root).expanduser().resolve()
    if not isinstance(astrbot_version, str) or not astrbot_version.strip():
        raise ValueError("AstrBot 版本标识不能为空")
    _legacy._validate_plugin_name(plugin_name)
    if not source.is_dir():
        raise ValueError(f"AstrBot 源码目录不存在或不是目录: {source}")

    root_was_present = root.exists()
    staged_plugin: Path | None = None
    runtime: LoaderRuntime | None = None
    metadata: Any | None = None
    loaded_plugin: Any | None = None
    baseline: RuntimeSnapshot | None = None
    report: LoaderReport | None = None
    failure: LoaderCheckError | None = None
    cleanup_errors: list[tuple[str, BaseException]] = []
    terminate_succeeded = False
    unbind_succeeded = False
    resource_cleanup_succeeded = False
    phase = "setup"
    previous_root = os.environ.get("ASTRBOT_ROOT")
    previous_reload = os.environ.get("ASTRBOT_RELOAD")
    inserted_paths: list[str] = []

    try:
        os.environ["ASTRBOT_ROOT"] = str(root)
        os.environ["ASTRBOT_RELOAD"] = "0"

        phase = "staging"
        staged_plugin = _legacy.stage_plugin(
            plugin_dir=plugin,
            astrbot_root=root,
            plugin_name=plugin_name,
        )
        plugin_version, _plugin_astrbot_spec = _legacy._read_plugin_metadata(
            staged_plugin,
            plugin_name,
        )
        inserted_paths = _legacy._prepend_sys_path(root, source)

        phase = "runtime"
        factory = runtime_factory or _build_official_runtime
        runtime = await _legacy._await_if_needed(
            factory(source, astrbot_version, root, plugin_name),
        )
        if not isinstance(runtime, LoaderRuntime):
            raise TypeError("runtime_factory 必须返回 LoaderRuntime")
        if not callable(runtime.snapshot_state):
            raise TypeError("LoaderRuntime 必须提供 snapshot_state()")
        baseline = runtime.snapshot_state()

        phase = "load"
        load_result = await _legacy._await_if_needed(
            runtime.plugin_manager.load(specified_dir_name=plugin_name),
        )
        if not isinstance(load_result, tuple) or not load_result:
            raise TypeError(
                "官方 PluginManager.load() 返回值不是 (success, error) 元组"
            )
        if not bool(load_result[0]):
            detail = load_result[1] if len(load_result) > 1 else None
            raise _legacy._official_load_failure(runtime, plugin_name, detail)

        phase = "registration"
        metadata = _legacy._find_metadata(runtime, plugin_name)
        if metadata is None:
            raise LoaderCheckError(
                "registration",
                f"official loader 成功返回，但未发现已注册插件 {plugin_name}",
            )
        loaded_plugin = getattr(metadata, "star_cls", None)
        if loaded_plugin is None:
            raise LoaderCheckError("instantiation", f"插件 {plugin_name} 没有可用实例")
        initialize = getattr(loaded_plugin, "initialize", None)
        if not callable(initialize):
            raise LoaderCheckError("initialize", "插件实例没有 initialize()")

        command_count, handler_count = _legacy._validate_dispatch_manifest(
            staged_plugin,
            metadata,
        )
        loaded_snapshot = runtime.snapshot_state()
        registered = _delta(baseline, loaded_snapshot)
        _assert_registration_is_observable(registered)

        report = LoaderReport(
            astrbot_version=astrbot_version,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            load_succeeded=True,
            initialize_succeeded=True,
            terminate_succeeded=False,
            unbind_succeeded=False,
            resource_cleanup_succeeded=False,
            command_count=command_count,
            handler_count=handler_count,
            registered_handler_count=len(registered.handlers),
            registered_tool_count=len(registered.tools),
            registered_web_api_count=len(registered.web_apis),
            background_task_count=len(registered.tasks),
        )
    except _CATCHABLE_ERRORS as error:
        failure = _legacy._wrap_error(phase, error)
    finally:
        if runtime is not None:
            if metadata is None:
                try:
                    metadata = _legacy._find_metadata(runtime, plugin_name)
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("registration", error))

            # 只有 load 已经形成完整报告时，才声明必须完成官方卸载契约；失败加载
            # 仍保留旧 harness 的 best-effort terminate，避免覆盖真正的加载错误。
            if report is not None and metadata is not None:
                try:
                    terminate = getattr(
                        runtime.plugin_manager, "_terminate_plugin", None
                    )
                    if not callable(terminate):
                        raise TypeError("官方 PluginManager 缺少 _terminate_plugin()")
                    await _legacy._await_if_needed(terminate(metadata))
                    terminate_succeeded = True
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("terminate", error))

                try:
                    module_path = getattr(metadata, "module_path", None)
                    if not isinstance(module_path, str) or not module_path:
                        raise TypeError(
                            "插件 metadata 缺少 module_path，无法执行官方 unbind"
                        )
                    unbind = getattr(runtime.plugin_manager, "_unbind_plugin", None)
                    if not callable(unbind):
                        raise TypeError("官方 PluginManager 缺少 _unbind_plugin()")
                    await _legacy._await_if_needed(
                        unbind(
                            getattr(metadata, "name", None) or plugin_name, module_path
                        ),
                    )
                    unbind_succeeded = True
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("unbind", error))

                if baseline is not None and callable(runtime.snapshot_state):
                    try:
                        _assert_no_runtime_residue(baseline, runtime.snapshot_state())
                        resource_cleanup_succeeded = True
                    except _CATCHABLE_ERRORS as error:
                        cleanup_errors.append(("resource cleanup", error))
            else:
                if loaded_plugin is None:
                    try:
                        loaded_plugin = _legacy._find_loaded_plugin(
                            runtime, plugin_name
                        )
                    except _CATCHABLE_ERRORS as error:
                        cleanup_errors.append(("registration", error))
                if loaded_plugin is not None:
                    try:
                        terminate = getattr(loaded_plugin, "terminate", None)
                        if not callable(terminate):
                            raise TypeError("插件实例没有 terminate()")
                        await _legacy._await_if_needed(terminate())
                    except _CATCHABLE_ERRORS as error:
                        cleanup_errors.append(("terminate", error))

            for callback in reversed(runtime.cleanup_callbacks):
                try:
                    await _legacy._await_if_needed(callback())
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("runtime cleanup", error))

        if not root_was_present and root.exists():
            try:
                shutil.rmtree(root)
            except _CATCHABLE_ERRORS as error:
                cleanup_errors.append(("temporary root cleanup", error))

        _legacy._remove_sys_path(inserted_paths)
        if previous_root is None:
            os.environ.pop("ASTRBOT_ROOT", None)
        else:
            os.environ["ASTRBOT_ROOT"] = previous_root
        if previous_reload is None:
            os.environ.pop("ASTRBOT_RELOAD", None)
        else:
            os.environ["ASTRBOT_RELOAD"] = previous_reload

    if failure is not None:
        for cleanup_phase, error in cleanup_errors:
            _legacy._append_error_note(failure, cleanup_phase, error)
        raise failure
    if cleanup_errors:
        cleanup_phase, first_error = cleanup_errors[0]
        cleanup_failure = _legacy._wrap_error(cleanup_phase, first_error)
        for extra_phase, error in cleanup_errors[1:]:
            _legacy._append_error_note(cleanup_failure, extra_phase, error)
        raise cleanup_failure
    if report is None:
        raise LoaderCheckError("unknown", "lifecycle 未生成检查报告")

    return replace(
        report,
        terminate_succeeded=terminate_succeeded,
        unbind_succeeded=unbind_succeeded,
        resource_cleanup_succeeded=resource_cleanup_succeeded,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用官方 AstrBot PluginManager 检查插件完整生命周期",
    )
    parser.add_argument("--astrbot-source", required=True, help="官方 AstrBot 源码目录")
    parser.add_argument(
        "--astrbot-version", required=True, help="被测 AstrBot 版本或 ref"
    )
    parser.add_argument("--plugin-dir", required=True, help="当前插件源码目录")
    parser.add_argument("--astrbot-root", required=True, help="临时 ASTRBOT_ROOT")
    parser.add_argument("--plugin-name", required=True, help="插件目录名")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plugin_dir = Path(args.plugin_dir).expanduser().resolve()
    try:
        report = asyncio.run(
            run_loader_check(
                astrbot_source=args.astrbot_source,
                astrbot_version=args.astrbot_version,
                plugin_dir=plugin_dir,
                astrbot_root=args.astrbot_root,
                plugin_name=args.plugin_name,
            ),
        )
    except _CATCHABLE_ERRORS as error:
        # 复用旧 harness 的完整 traceback + 凭据脱敏输出。
        print(
            _legacy._format_failure(
                error,
                astrbot_version=args.astrbot_version,
                plugin_name=args.plugin_name,
                plugin_dir=plugin_dir,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        "AstrBot plugin lifecycle passed: "
        f"astrbot={report.astrbot_version}, "
        f"plugin={report.plugin_name}@{report.plugin_version}, "
        f"commands={report.command_count}, handlers={report.registered_handler_count}, "
        f"tools={report.registered_tool_count}, web_apis={report.registered_web_api_count}, "
        f"background_tasks={report.background_task_count}, "
        "terminate=ok, unbind=ok, cleanup=ok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
