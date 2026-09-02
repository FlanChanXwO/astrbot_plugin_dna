"""使用官方 AstrBot PluginManager 验证插件加载与生命周期。

该脚本只用于 PR/本地兼容性检查。它会把插件复制到临时 ``ASTRBOT_ROOT``，
再直接调用官方 ``PluginManager.load()``；不连接真实平台、不读取真实账号，且
只把插件初始化所需的本地文件写入临时根目录。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

_STABLE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXCLUDED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data",
    "cookies.json",
    "cookie.json",
    "cookies.txt",
    "secrets.json",
    "token.json",
}

_T = TypeVar("_T")


@dataclass(slots=True)
class LoaderRuntime:
    """官方 Context/PluginManager 及其 harness 专用清理回调。"""

    context: Any
    plugin_manager: Any
    loaded_plugin: Any | None = None
    cleanup_callbacks: tuple[Callable[[], object], ...] = ()


@dataclass(frozen=True, slots=True)
class LoaderReport:
    """一次 loader 检查的可审计结果。"""

    astrbot_version: str
    plugin_name: str
    plugin_version: str
    load_succeeded: bool
    initialize_succeeded: bool
    terminate_succeeded: bool
    command_count: int
    handler_count: int


class LoaderCheckError(RuntimeError):
    """带有明确阶段名的 loader 检查错误。"""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"[{phase}] {message}")


def select_latest_stable_version(tags: Iterable[str]) -> str:
    """从 tag 中选择最高的正式三段式 SemVer，排除所有预发布版本。"""

    candidates: list[tuple[tuple[int, int, int], str]] = []
    for raw_tag in tags:
        if not isinstance(raw_tag, str):
            continue
        tag = raw_tag.strip()
        match = _STABLE_VERSION_RE.fullmatch(tag)
        if match is None:
            continue
        candidates.append((tuple(int(part) for part in match.groups()), tag))
    if not candidates:
        raise ValueError("没有找到符合正式 stable 版本格式的 AstrBot release tag")
    return max(candidates, key=lambda item: item[0])[1]


def _is_excluded_name(name: str) -> bool:
    lowered = name.lower()
    if name in _EXCLUDED_NAMES or lowered in _EXCLUDED_NAMES:
        return True
    if name.startswith(".env"):
        return True
    if lowered.endswith((".sqlite", ".sqlite3", ".db", ".log", ".pyc")):
        return True
    return False


def _validate_plugin_name(plugin_name: str) -> None:
    if _PLUGIN_NAME_RE.fullmatch(plugin_name) is None:
        raise ValueError(
            f"插件名必须是可导入的单一 Python 目录名，实际为 {plugin_name!r}",
        )


def _copy_plugin_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for entry in source.iterdir():
        if _is_excluded_name(entry.name):
            continue
        if entry.is_symlink():
            # 不跟随可能指向仓库外或宿主机秘密的链接，避免 staging 越界。
            raise ValueError(f"插件源码包含不允许 staging 的符号链接: {entry}")
        target = destination / entry.name
        if entry.is_dir():
            _copy_plugin_tree(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)
        else:
            raise OSError(f"无法 staging 非普通文件: {entry}")


def stage_plugin(
    *,
    plugin_dir: str | Path,
    astrbot_root: str | Path,
    plugin_name: str,
) -> Path:
    """把插件当前源码复制到临时 AstrBot 根下并排除运行期/仓库数据。"""

    source = Path(plugin_dir).expanduser().resolve()
    root = Path(astrbot_root).expanduser().resolve()
    _validate_plugin_name(plugin_name)
    if not source.is_dir():
        raise ValueError(f"插件目录不存在或不是目录: {source}")

    # 防止把目标目录放进源码目录后递归复制；临时根本来就不应是源码子目录。
    if root == source or root in source.parents:
        raise ValueError("ASTRBOT_ROOT 不能位于插件源码目录内")
    if root.exists() and not root.is_dir():
        raise ValueError(f"ASTRBOT_ROOT 不是目录: {root}")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"ASTRBOT_ROOT 必须为空的临时目录: {root}")

    destination = root / "data" / "plugins" / plugin_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_plugin_tree(source, destination)
    return destination


def _read_plugin_metadata(plugin_dir: Path, plugin_name: str) -> tuple[str, str]:
    metadata_path = next(
        (
            plugin_dir / filename
            for filename in ("metadata.yaml", "metadata.yml")
            if (plugin_dir / filename).is_file()
        ),
        None,
    )
    if metadata_path is None:
        raise LoaderCheckError("metadata", "缺少 metadata.yaml 或 metadata.yml")

    try:
        import yaml

        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except BaseException as error:
        raise LoaderCheckError(
            "metadata",
            f"无法读取 {metadata_path.name}: {type(error).__name__}: {error}",
        ) from error
    if not isinstance(raw, Mapping):
        raise LoaderCheckError("metadata", "metadata 必须解析为对象")

    name = raw.get("name")
    version = raw.get("version")
    astrbot_version = raw.get("astrbot_version")
    if not isinstance(name, str) or not name.strip():
        raise LoaderCheckError("metadata", "metadata.name 不能为空")
    if name != plugin_name:
        raise LoaderCheckError(
            "metadata",
            f"metadata.name={name!r} 与插件目录名 {plugin_name!r} 不一致",
        )
    if not isinstance(version, str) or not version.strip():
        raise LoaderCheckError("metadata", "metadata.version 不能为空")
    if not isinstance(astrbot_version, str) or not astrbot_version.strip():
        raise LoaderCheckError("metadata", "metadata.astrbot_version 不能为空")
    return version, astrbot_version


def _write_ci_plugin_config(astrbot_root: Path, plugin_name: str) -> None:
    config_path = astrbot_root / "data" / "config" / f"{plugin_name}_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "login": {"port": 0},
                "sign_in": {"scheduled_enabled": False},
                "notifications": {"announcement_enabled": False},
                "agent_tools": {"enabled": False},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _prepend_sys_path(*paths: Path) -> list[str]:
    inserted: list[str] = []
    for path in paths:
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
            inserted.append(value)
    return inserted


def _remove_sys_path(values: Sequence[str]) -> None:
    for value in values:
        try:
            sys.path.remove(value)
        except ValueError:
            # 同一进程内若官方模块主动重排 sys.path，目标值已不在路径中。
            continue


def _build_official_context(context_cls: type[Any], config: Any) -> Any:
    """按官方 Context 的真实签名传入最小依赖，不自定义替代 Context。"""

    parameters = inspect.signature(context_cls).parameters
    kwargs: dict[str, Any] = {}
    for name, parameter in parameters.items():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if name in {"self", "cls"}:
            continue
        if name in {"config", "astrbot_config"}:
            kwargs[name] = config
        elif parameter.default is inspect.Parameter.empty:
            # Context 构造函数只保存这些宿主管理器；loader 检查不启动真实平台。
            kwargs[name] = None
    if "config" not in kwargs and "astrbot_config" not in kwargs:
        raise TypeError("官方 Context 构造函数没有可识别的配置参数")
    return context_cls(**kwargs)


class _ResourcePreheatGuard:
    """在官方导入插件后、执行 initialize 前禁用外部资源预热。"""

    def __init__(self, plugin_name: str) -> None:
        self._plugin_name = plugin_name
        self._service_cls: type[Any] | None = None
        self._original_start_preheat: Any | None = None

    def install_for_imported_plugin(self, root_dir_name: str) -> None:
        if root_dir_name != self._plugin_name or self._service_cls is not None:
            return
        module_name = (
            f"data.plugins.{self._plugin_name}.src.modules.operations.resource_service"
        )
        module = sys.modules.get(module_name)
        if module is None:
            # 插件导入失败时必须让官方 loader 自己报告原始 import 错误。
            return
        service_cls = getattr(module, "ResourceUpdateService", None)
        original = getattr(service_cls, "start_preheat", None)
        if service_cls is None or not callable(original):
            return

        async def _skip_preheat(_self: Any) -> None:
            """loader CI 不把外部公共资源仓库可用性作为通过条件。"""

        self._service_cls = service_cls
        self._original_start_preheat = original
        service_cls.start_preheat = _skip_preheat

    def restore(self) -> None:
        if self._service_cls is not None and self._original_start_preheat is not None:
            self._service_cls.start_preheat = self._original_start_preheat
            self._service_cls = None
            self._original_start_preheat = None


def _tracking_manager_class(
    manager_cls: type[Any],
    *,
    plugin_name: str,
    on_plugin_import: Callable[[str], object],
) -> type[Any]:
    has_cleanup_hook = hasattr(manager_cls, "_cleanup_plugin_state")
    has_import_hook = hasattr(manager_cls, "_import_plugin_with_dependency_recovery")
    if not has_cleanup_hook and not has_import_hook:
        return manager_cls

    class TrackingPluginManager(manager_cls):
        """在官方清理前保留失败初始化实例，并注入 CI 预热隔离。"""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.captured_metadata: list[Any] = []
            super().__init__(*args, **kwargs)

        async def _import_plugin_with_dependency_recovery(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            imported_module = await _await_if_needed(
                super()._import_plugin_with_dependency_recovery(*args, **kwargs),
            )
            root_dir_name = kwargs.get("root_dir_name")
            if root_dir_name is None and len(args) >= 3:
                root_dir_name = args[2]
            if root_dir_name == plugin_name:
                await _await_if_needed(on_plugin_import(plugin_name))
            return imported_module

        def _cleanup_plugin_state(self, *args: Any, **kwargs: Any) -> Any:
            get_all_stars = getattr(self.context, "get_all_stars", None)
            if callable(get_all_stars):
                self.captured_metadata.extend(tuple(get_all_stars()))
            return super()._cleanup_plugin_state(*args, **kwargs)

    return TrackingPluginManager


def _build_official_runtime(
    astrbot_source: Path,
    _astrbot_version: str,
    astrbot_root: Path,
    plugin_name: str,
) -> LoaderRuntime:
    """建立官方 Context/PluginManager，供同一套 loader 逻辑调用。"""

    _write_ci_plugin_config(astrbot_root, plugin_name)
    resource_guard = _ResourcePreheatGuard(plugin_name)
    try:
        from astrbot.api.star import Context
        from astrbot.core import AstrBotConfig
        from astrbot.core.star.star_manager import PluginManager

        config = AstrBotConfig(
            config_path=str(astrbot_root / "data" / "cmd_config.json"),
        )
        context = _build_official_context(Context, config)
        # 避免同一解释器内的测试/重复调用复用旧 Web API 列表。
        if isinstance(getattr(Context, "registered_web_apis", None), list):
            Context.registered_web_apis = []
        manager_cls = _tracking_manager_class(
            PluginManager,
            plugin_name=plugin_name,
            on_plugin_import=resource_guard.install_for_imported_plugin,
        )
        manager = manager_cls(context, config)
    except BaseException:
        resource_guard.restore()
        raise
    return LoaderRuntime(
        context=context,
        plugin_manager=manager,
        cleanup_callbacks=(resource_guard.restore,),
    )


def _find_metadata(runtime: LoaderRuntime, plugin_name: str) -> Any | None:
    get_all_stars = getattr(runtime.context, "get_all_stars", None)
    if not callable(get_all_stars):
        raise LoaderCheckError("registration", "官方 Context 缺少 get_all_stars()")
    stars = get_all_stars()
    if stars is None:
        raise LoaderCheckError("registration", "官方 loader 未返回 Star registry")
    for metadata in reversed(tuple(stars)):
        if (
            getattr(metadata, "root_dir_name", None) == plugin_name
            or getattr(metadata, "name", None) == plugin_name
        ):
            return metadata
    return None


def _find_loaded_plugin(runtime: LoaderRuntime, plugin_name: str) -> Any | None:
    if runtime.loaded_plugin is not None:
        return runtime.loaded_plugin

    metadata = _find_metadata(runtime, plugin_name)
    if metadata is not None:
        plugin = getattr(metadata, "star_cls", None)
        if plugin is not None:
            return plugin

    manager = runtime.plugin_manager
    for captured_metadata in getattr(manager, "captured_metadata", ()):
        if (
            getattr(captured_metadata, "root_dir_name", None) == plugin_name
            or getattr(captured_metadata, "name", None) == plugin_name
        ):
            plugin = getattr(captured_metadata, "star_cls", None)
            if plugin is not None:
                return plugin
    for attribute in ("captured_plugin", "loaded_plugin", "plugin"):
        plugin = getattr(manager, attribute, None)
        if plugin is not None:
            return plugin
    return None


def _validate_dispatch_manifest(
    staged_plugin: Path,
    metadata: Any,
) -> tuple[int, int]:
    module = getattr(metadata, "module", None)
    registry = getattr(module, "COMMAND_REGISTRY", None)
    if registry is None:
        raise LoaderCheckError("registration", "插件未导出 COMMAND_REGISTRY")
    try:
        specs = tuple(registry)
    except BaseException as error:
        raise LoaderCheckError(
            "registration",
            f"COMMAND_REGISTRY 不可迭代: {type(error).__name__}: {error}",
        ) from error
    if not specs:
        raise LoaderCheckError("registration", "COMMAND_REGISTRY 为空")

    command_ids: list[str] = []
    for spec in specs:
        command_id = getattr(spec, "id", None)
        if not isinstance(command_id, str) or not command_id:
            raise LoaderCheckError("registration", "命令 registry 含无效 id")
        command_ids.append(command_id)
    if len(set(command_ids)) != len(command_ids):
        raise LoaderCheckError("registration", "命令 registry 含重复 id")

    manifest_path = staged_plugin / "commands.json"
    if not manifest_path.is_file():
        raise LoaderCheckError("registration", "缺少 commands.json 分发表")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except BaseException as error:
        raise LoaderCheckError(
            "registration",
            f"无法读取 commands.json: {type(error).__name__}: {error}",
        ) from error
    if not isinstance(manifest, list):
        raise LoaderCheckError("registration", "commands.json 必须是数组")
    manifest_ids = [
        item.get("id") if isinstance(item, Mapping) else None for item in manifest
    ]
    if manifest_ids != command_ids:
        raise LoaderCheckError(
            "registration",
            "commands.json 与 COMMAND_REGISTRY 的命令顺序或内容不一致",
        )

    handlers = tuple(getattr(metadata, "star_handler_full_names", ()) or ())
    if len(handlers) < len(command_ids):
        raise LoaderCheckError(
            "registration",
            f"官方 loader 注册的 handler 数量不足: {len(handlers)} < {len(command_ids)}",
        )
    return len(command_ids), len(handlers)


def _infer_phase_from_traceback_text(default_phase: str, error_trace: str) -> str:
    if default_phase == "load" and re.search(r", in _?initialize\b", error_trace):
        return "initialize"
    return default_phase


def _official_load_failure(
    runtime: LoaderRuntime,
    plugin_name: str,
    detail: object,
) -> LoaderCheckError:
    """保留官方 loader 捕获的原始失败记录，而不是把它降级为空错误。"""

    record: Mapping[str, object] | None = None
    records = getattr(runtime.plugin_manager, "failed_plugin_dict", None)
    if isinstance(records, Mapping):
        candidate = records.get(plugin_name)
        if isinstance(candidate, Mapping):
            record = candidate

    error_text = record.get("error") if record is not None else None
    traceback_text = record.get("traceback") if record is not None else None
    phase = _infer_phase_from_traceback_text(
        "load",
        traceback_text if isinstance(traceback_text, str) else "",
    )
    details = ["official loader returned failure"]
    if isinstance(error_text, str) and error_text.strip():
        details.append(f"plugin error: {error_text}")
    if detail is not None and str(detail).strip():
        details.append(f"loader detail: {detail}")
    if isinstance(traceback_text, str) and traceback_text.strip():
        details.append(f"official traceback:\n{traceback_text}")
    return LoaderCheckError(phase, "\n".join(details))


def _await_if_needed(value: _T | Awaitable[_T]) -> Awaitable[_T]:
    if inspect.isawaitable(value):
        return value

    async def _resolved() -> _T:
        return value

    return _resolved()


def _infer_phase(default_phase: str, error: BaseException) -> str:
    if default_phase == "load":
        for frame in traceback.extract_tb(error.__traceback__):
            if frame.name in {"initialize", "_initialize"}:
                return "initialize"
    return default_phase


def _wrap_error(default_phase: str, error: BaseException) -> LoaderCheckError:
    if isinstance(error, LoaderCheckError):
        return error
    phase = _infer_phase(default_phase, error)
    wrapped = LoaderCheckError(
        phase,
        f"{type(error).__name__}: {error}",
    )
    wrapped.__cause__ = error
    return wrapped


def _append_error_note(target: BaseException, phase: str, error: BaseException) -> None:
    target.add_note(
        f"cleanup phase={phase} failed: {type(error).__name__}: {error}\n"
        + "".join(traceback.format_exception(type(error), error, error.__traceback__)),
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
    """执行一次官方 loader 生命周期检查；``runtime_factory`` 仅供离线契约测试注入。"""

    source = Path(astrbot_source).expanduser().resolve()
    plugin = Path(plugin_dir).expanduser().resolve()
    root = Path(astrbot_root).expanduser().resolve()
    if not isinstance(astrbot_version, str) or not astrbot_version.strip():
        raise ValueError("AstrBot 版本标识不能为空")
    _validate_plugin_name(plugin_name)
    if not source.is_dir():
        raise ValueError(f"AstrBot 源码目录不存在或不是目录: {source}")

    root_was_present = root.exists()
    staged_plugin: Path | None = None
    runtime: LoaderRuntime | None = None
    loaded_plugin: Any | None = None
    report: LoaderReport | None = None
    failure: LoaderCheckError | None = None
    cleanup_errors: list[tuple[str, BaseException]] = []
    phase = "setup"
    previous_root = os.environ.get("ASTRBOT_ROOT")
    previous_reload = os.environ.get("ASTRBOT_RELOAD")
    inserted_paths: list[str] = []

    try:
        os.environ["ASTRBOT_ROOT"] = str(root)
        # 避免官方 PluginManager 启动热加载 watcher；CI 只验证一次显式生命周期。
        os.environ["ASTRBOT_RELOAD"] = "0"
        phase = "staging"
        staged_plugin = stage_plugin(
            plugin_dir=plugin,
            astrbot_root=root,
            plugin_name=plugin_name,
        )
        plugin_version, _plugin_astrbot_spec = _read_plugin_metadata(
            staged_plugin,
            plugin_name,
        )
        inserted_paths = _prepend_sys_path(root, source)

        phase = "runtime"
        factory = runtime_factory or _build_official_runtime
        runtime = await _await_if_needed(
            factory(source, astrbot_version, root, plugin_name),
        )
        if not isinstance(runtime, LoaderRuntime):
            raise TypeError("runtime_factory 必须返回 LoaderRuntime")

        phase = "load"
        load_result = await _await_if_needed(
            runtime.plugin_manager.load(specified_dir_name=plugin_name),
        )
        if not isinstance(load_result, tuple) or not load_result:
            raise TypeError(
                "官方 PluginManager.load() 返回值不是 (success, error) 元组"
            )
        if not bool(load_result[0]):
            detail = load_result[1] if len(load_result) > 1 else None
            raise _official_load_failure(runtime, plugin_name, detail)

        phase = "registration"
        metadata = _find_metadata(runtime, plugin_name)
        if metadata is None:
            raise LoaderCheckError(
                "registration",
                f"official loader 成功返回，但未发现已注册插件 {plugin_name}",
            )
        loaded_plugin = getattr(metadata, "star_cls", None)
        if loaded_plugin is None:
            raise LoaderCheckError(
                "instantiation",
                f"插件 {plugin_name} 没有可用实例",
            )
        initialize = getattr(loaded_plugin, "initialize", None)
        if not callable(initialize):
            raise LoaderCheckError("initialize", "插件实例没有 initialize()")
        command_count, handler_count = _validate_dispatch_manifest(
            staged_plugin,
            metadata,
        )
        report = LoaderReport(
            astrbot_version=astrbot_version,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            load_succeeded=True,
            initialize_succeeded=True,
            terminate_succeeded=False,
            command_count=command_count,
            handler_count=handler_count,
        )
    except BaseException as error:
        failure = _wrap_error(phase, error)
    finally:
        if runtime is not None:
            try:
                if loaded_plugin is None:
                    loaded_plugin = _find_loaded_plugin(runtime, plugin_name)
            except BaseException as error:
                cleanup_errors.append(("registration", error))

            if loaded_plugin is not None:
                try:
                    terminate = getattr(loaded_plugin, "terminate", None)
                    if not callable(terminate):
                        raise TypeError("插件实例没有 terminate()")
                    await _await_if_needed(terminate())
                except BaseException as error:
                    cleanup_errors.append(("terminate", error))

            for callback in reversed(runtime.cleanup_callbacks):
                try:
                    await _await_if_needed(callback())
                except BaseException as error:
                    cleanup_errors.append(("runtime cleanup", error))

        # 只有本次调用创建的根目录才由 harness 删除，避免误删调用方目录。
        if not root_was_present and root.exists():
            try:
                shutil.rmtree(root)
            except BaseException as error:
                cleanup_errors.append(("temporary root cleanup", error))

        _remove_sys_path(inserted_paths)
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
            _append_error_note(failure, cleanup_phase, error)
        raise failure
    if cleanup_errors:
        cleanup_phase, first_error = cleanup_errors[0]
        cleanup_failure = _wrap_error(cleanup_phase, first_error)
        for extra_phase, error in cleanup_errors[1:]:
            _append_error_note(cleanup_failure, extra_phase, error)
        raise cleanup_failure
    if report is None:
        raise LoaderCheckError("unknown", "loader 未生成检查报告")
    return replace(report, terminate_succeeded=True)


def _git_commit(plugin_dir: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(plugin_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    return commit or "unavailable"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用官方 AstrBot PluginManager.load() 检查插件生命周期",
    )
    parser.add_argument("--astrbot-source", required=True, help="官方 AstrBot 源码目录")
    parser.add_argument(
        "--astrbot-version", required=True, help="被测 AstrBot 版本或 ref"
    )
    parser.add_argument("--plugin-dir", required=True, help="当前插件源码目录")
    parser.add_argument(
        "--astrbot-root", required=True, help="本次检查使用的临时 ASTRBOT_ROOT"
    )
    parser.add_argument(
        "--plugin-name", required=True, help="插件目录名，例如 astrbot_plugin_dnaby"
    )
    return parser


def _format_failure(
    error: BaseException,
    *,
    astrbot_version: str,
    plugin_name: str,
    plugin_dir: Path,
) -> str:
    phase = getattr(error, "phase", "unknown")
    lines = [
        f"phase: {phase}",
        f"error_type: {type(error).__name__}",
        f"error: {error}",
        f"astrbot_version: {astrbot_version}",
        f"plugin: {plugin_name}",
        f"commit: {_git_commit(plugin_dir)}",
        "full traceback:",
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
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
    except BaseException as error:
        print(
            _format_failure(
                error,
                astrbot_version=args.astrbot_version,
                plugin_name=args.plugin_name,
                plugin_dir=plugin_dir,
            ),
            file=sys.stderr,
        )
        return 1

    print(f"AstrBot version: {report.astrbot_version}")
    print(f"Plugin: {report.plugin_name} ({report.plugin_version})")
    print(
        "load + initialize: success "
        f"(commands={report.command_count}, handlers={report.handler_count})",
    )
    print("terminate: success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
