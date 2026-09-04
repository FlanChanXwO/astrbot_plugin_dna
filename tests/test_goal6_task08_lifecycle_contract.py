"""Goal 6 T08：生命周期轻量化与可释放性的 Red 契约。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.entry.lifecycle import LifecycleHook, PluginLifecycle
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.resources import ResourceSnapshotCoordinator


class _CapturedLifecycle:
    """只记录 bootstrap 注册的生命周期 hook，避免 Red 测试启动真实后台任务。"""

    def __init__(
        self,
        *,
        start_hooks: Iterable[LifecycleHook] = (),
        stop_hooks: Iterable[LifecycleHook] = (),
        finalizer_hooks: Iterable[LifecycleHook] = (),
    ) -> None:
        self.start_hooks = tuple(start_hooks)
        self.stop_hooks = tuple(stop_hooks)
        self.finalizer_hooks = tuple(finalizer_hooks)


class _ResourceServiceSpy:
    """用于确认资源服务不会被隐式预热。"""

    async def start_preheat(self) -> None:
        raise AssertionError("生命周期不应注册资源预热")

    async def stop(self) -> None:
        return None


class _RestTransportSpy:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("rest-close")


class _BusinessWebSocketSpy:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close_all(self) -> None:
        self.events.append("ws-close")


class _LoginFlowSpy:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _build_runtime_for_hook_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    services: Mapping[str, object] | None = None,
) -> _CapturedLifecycle:
    """构造一次 runtime 并返回 bootstrap 注册的 hook。"""

    import src.bootstrap as bootstrap

    captured: _CapturedLifecycle | None = None

    def capture_lifecycle(**kwargs: Any) -> _CapturedLifecycle:
        nonlocal captured
        captured = _CapturedLifecycle(**kwargs)
        return captured

    monkeypatch.setattr(bootstrap, "PluginLifecycle", capture_lifecycle)
    monkeypatch.setattr(
        ResourceSnapshotCoordinator,
        "initialize",
        lambda _self: None,
    )
    bootstrap.build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=AsyncDatabase(tmp_path / "runtime.sqlite3"),
        services=services,
    )
    assert captured is not None
    return captured


def _is_bound_hook(hook: LifecycleHook, owner: object, name: str) -> bool:
    return (
        getattr(hook, "__self__", None) is owner
        and getattr(hook, "__name__", "") == name
    )


def test_build_runtime_does_not_run_full_resource_initialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """构造 runtime 不能调用包含完整 validator 的旧 initialize。"""

    calls: list[str] = []

    def record_full_initialization(_self: ResourceSnapshotCoordinator) -> None:
        calls.append("full-resource-initialize")
        return None

    import src.bootstrap as bootstrap

    monkeypatch.setattr(
        ResourceSnapshotCoordinator, "initialize", record_full_initialization
    )
    monkeypatch.setattr(bootstrap, "PluginLifecycle", _CapturedLifecycle)

    bootstrap.build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {},
        database=AsyncDatabase(tmp_path / "runtime.sqlite3"),
    )

    assert calls == []


def test_build_runtime_does_not_register_resource_preheat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """启动 hook 不得创建会触发 Git/同步的资源预热任务。"""

    resource_service = _ResourceServiceSpy()
    lifecycle = _build_runtime_for_hook_capture(
        monkeypatch,
        tmp_path,
        services={"resource_update_service": resource_service},
    )

    assert not any(
        _is_bound_hook(hook, resource_service, "start_preheat")
        for hook in lifecycle.start_hooks
    )


def test_build_runtime_start_hooks_do_not_include_active_auth_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """启动只注册 listener/scheduler，不注册 credential validation 或授权探测。"""

    lifecycle = _build_runtime_for_hook_capture(
        monkeypatch,
        tmp_path,
        services={"login_flow": _LoginFlowSpy()},
    )
    forbidden_fragments = (
        "credential",
        "validate",
        "refresh",
        "probe",
        "auth",
    )

    hook_names = [
        f"{getattr(hook, '__qualname__', '')} {getattr(hook, '__name__', '')}"
        for hook in lifecycle.start_hooks
    ]
    assert not any(
        fragment in name.lower()
        for name in hook_names
        for fragment in forbidden_fragments
    )


@pytest.mark.asyncio
async def test_dna_api_close_releases_rest_and_business_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """统一 App facade 的关闭必须同时释放 REST session 和业务 WS 连接池。"""

    from src.utils.api import ws_manager as ws_manager_module
    from src.utils.api.requests import DNAApi

    events: list[str] = []
    websocket = _BusinessWebSocketSpy(events)
    monkeypatch.setattr(ws_manager_module, "get_ws_manager", lambda: websocket)

    api = DNAApi(app_transport=_RestTransportSpy(events))
    await api.close()

    assert events == ["rest-close", "ws-close"]


@pytest.mark.asyncio
async def test_partial_initialize_cleans_only_completed_steps() -> None:
    """初始化部分失败时，只逆序释放已成功完成的步骤。"""

    events: list[str] = []

    async def start_one() -> None:
        events.append("start-one")

    async def start_two() -> None:
        events.append("start-two")
        raise RuntimeError("start-two failed")

    async def stop_one() -> None:
        events.append("stop-one")

    async def stop_two() -> None:
        events.append("stop-two")

    lifecycle = PluginLifecycle(
        start_hooks=(start_one, start_two),
        stop_hooks=(stop_one, stop_two),
    )

    with pytest.raises(RuntimeError, match="start-two failed"):
        await lifecycle.initialize()

    assert events == ["start-one", "start-two", "stop-one"]
    assert lifecycle.started is False


@pytest.mark.asyncio
async def test_terminate_cancels_scheduler_before_transport_and_database() -> None:
    """terminate 必须先排空后台任务，再释放网络和数据库资源。"""

    events: list[str] = []
    task_started = asyncio.Event()
    scheduler_task: asyncio.Task[None] | None = None

    async def scheduler_start() -> None:
        nonlocal scheduler_task

        async def wait_for_shutdown() -> None:
            task_started.set()
            await asyncio.Event().wait()

        scheduler_task = asyncio.create_task(wait_for_shutdown())

    async def scheduler_stop() -> None:
        assert scheduler_task is not None
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, return_exceptions=True)
        events.append("scheduler-stop")

    async def rest_close() -> None:
        events.append("rest-close")

    async def websocket_close() -> None:
        events.append("ws-close")

    async def database_close() -> None:
        events.append("database-close")

    lifecycle = PluginLifecycle(
        start_hooks=(scheduler_start,),
        stop_hooks=(database_close, websocket_close, rest_close, scheduler_stop),
    )

    await lifecycle.initialize()
    await task_started.wait()
    await lifecycle.terminate()

    assert events == [
        "scheduler-stop",
        "rest-close",
        "ws-close",
        "database-close",
    ]


@pytest.mark.asyncio
async def test_lifecycle_records_total_and_phase_timings() -> None:
    """初始化和终止都应保留总耗时及各阶段耗时。"""

    async def start() -> None:
        return None

    async def stop() -> None:
        return None

    lifecycle = PluginLifecycle(start_hooks=(start,), stop_hooks=(stop,))

    await lifecycle.initialize()
    initialize_timings = lifecycle.last_timings
    assert (
        initialize_timings["initialize.total"]
        >= initialize_timings["initialize.phase_0"]
        >= 0
    )

    await lifecycle.terminate()
    terminate_timings = lifecycle.last_timings
    assert (
        terminate_timings["terminate.total"]
        >= terminate_timings["terminate.phase_0"]
        >= 0
    )


@pytest.mark.asyncio
async def test_lifecycle_runs_finalizers_after_steps() -> None:
    """传输和数据库等最终资源应在所有业务步骤停止后按声明顺序释放。"""

    events: list[str] = []

    async def start() -> None:
        events.append("start")

    async def stop() -> None:
        events.append("stop")

    async def close_transport() -> None:
        events.append("transport-close")

    async def close_database() -> None:
        events.append("database-close")

    lifecycle = PluginLifecycle(
        start_hooks=(start,),
        stop_hooks=(stop,),
        finalizer_hooks=(close_transport, close_database),
    )

    await lifecycle.initialize()
    await lifecycle.terminate()

    assert events == ["start", "stop", "transport-close", "database-close"]
