"""Issue #95 生命周期契约：数据库 schema 必须早于所有消费者就绪。

这些测试固定的是启动顺序本身：只要有人把 ``database_migration.initialize`` 从
``start_hooks`` 移除、后移，或删掉某个阶段的 stop hook，测试就会失败。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bootstrap import build_runtime
from src.entry.lifecycle import _hook_label
from src.infrastructure import RuntimeDataLayout
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.persistence.migrations import (
    DatabaseMigration,
    default_plugin_root,
)


class _Context:
    """只实现 runtime 组装需要的宿主接口。"""

    def register_web_api(self, *args: object) -> None:
        return None


def _short_label(hook: object, index: int) -> str:
    """去掉嵌套函数前缀，返回可用于断言的稳定 hook 名称。"""

    return _hook_label(hook, index).removeprefix("build_runtime.<locals>.")


def _instrument_lifecycle(runtime, recorder: list[str]) -> dict[str, int]:
    """包装真实启动 hook 记录顺序，并返回包装前的阶段索引。"""

    indices: dict[str, int] = {}
    wrapped_hooks: list[object] = []
    for index, hook in enumerate(runtime.lifecycle._start_hooks):
        label = _short_label(hook, index)
        indices[label] = index

        async def _wrapped(_hook=hook, _index=index) -> None:
            recorder.append(_short_label(_hook, _index))
            await _hook()

        wrapped_hooks.append(_wrapped)
    runtime.lifecycle._start_hooks = tuple(wrapped_hooks)

    wrapped_stops: list[object] = []
    for index, hook in enumerate(runtime.lifecycle._stop_hooks):
        label = _short_label(hook, index)

        async def _wrapped_stop(_hook=hook, _index=index) -> None:
            recorder.append(_short_label(_hook, _index))
            await _hook()

        wrapped_stops.append(_wrapped_stop)
    runtime.lifecycle._stop_hooks = tuple(wrapped_stops)
    return indices


def _build_runtime(tmp_path, recorder: list[str], database: AsyncDatabase):
    """组装一个所有生命周期阶段都会写入 ``recorder`` 的 runtime。"""

    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    runtime = build_runtime(
        _Context(),
        {},
        database=database,
        runtime_data_layout=layout,
        services={
            "database_migration": DatabaseMigration(
                database,
                plugin_root=default_plugin_root(),
            ),
        },
    )
    return layout, runtime, _instrument_lifecycle(runtime, recorder)

MIGRATION_STAGE = "DatabaseMigration.initialize"
CONSUMER_STAGES = (
    "LoginFlowCoordinator.start",
    "WebRegistrar.initialize",
    "CacheMaintenance.start",
    "SignScheduler.start",
    "NoticesScheduler.start",
    "ClientUpdatesScheduler.start",
    "AgentToolsLifecycle.start",
)

# (第 N 个启动阶段, 第 N 个停止 hook)；索引必须严格一一对应。
EXPECTED_HOOK_PAIRS = (
    (MIGRATION_STAGE, "_stop_database_migration"),
    ("ImageFetcher.start", "_stop_image_fetcher"),
    ("_initialize_resource_views", "_stop_resource_views"),
    ("LoginFlowCoordinator.start", "LoginFlowCoordinator.stop"),
    ("ClientUpdateService.initialize", "_stop_client_update_service"),
    ("WebRegistrar.initialize", "WebRegistrar.stop"),
    ("CacheMaintenance.start", "CacheMaintenance.stop"),
    ("SignScheduler.start", "SignScheduler.stop"),
    ("NoticesScheduler.start", "NoticesScheduler.stop"),
    ("ClientUpdatesScheduler.start", "ClientUpdatesScheduler.stop"),
    ("AgentToolsLifecycle.start", "AgentToolsLifecycle.stop"),
)


def _replace_start_hook(runtime, index: int, replacement) -> None:
    runtime.lifecycle._start_hooks = (
        *runtime.lifecycle._start_hooks[:index],
        replacement,
        *runtime.lifecycle._start_hooks[index + 1 :],
    )


@pytest.mark.asyncio
async def test_database_migration_precedes_every_database_consumer(tmp_path) -> None:
    """迁移必须早于 LoginFlow、Web 和所有 scheduler。"""

    recorder: list[str] = []
    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase.from_data_dir(layout.data_dir)
    _layout, runtime, _stages = _build_runtime(tmp_path, recorder, database)
    try:
        await runtime.initialize()

        assert recorder[0] == MIGRATION_STAGE
        for consumer in CONSUMER_STAGES:
            assert consumer in recorder, consumer
            assert recorder.index(MIGRATION_STAGE) < recorder.index(consumer), consumer
        assert layout.database_path.is_file()
    finally:
        await runtime.terminate()
        await database.dispose()


@pytest.mark.asyncio
async def test_migration_failure_stops_startup_before_consumers(tmp_path) -> None:
    """迁移失败时 LoginFlow / Web / Scheduler 都不会进入可用状态。"""

    recorder: list[str] = []
    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase.from_data_dir(layout.data_dir)

    async def _failing_initialize() -> None:
        raise RuntimeError("migration-fixture-failure")

    runtime = build_runtime(
        _Context(),
        {},
        database=database,
        runtime_data_layout=layout,
        services={
            "database_migration": SimpleNamespace(initialize=_failing_initialize),
        },
    )
    _instrument_lifecycle(runtime, recorder)

    try:
        with pytest.raises(RuntimeError, match="migration-fixture-failure"):
            await runtime.initialize()

        assert not layout.database_path.exists()
        for consumer in CONSUMER_STAGES:
            assert consumer not in recorder, consumer
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_startup_failure_rolls_back_only_entered_phases_in_reverse(
    tmp_path,
) -> None:
    """中途失败时按已进入阶段逆序清理，不能 stop 未启动的后续阶段。"""

    recorder: list[str] = []
    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase.from_data_dir(layout.data_dir)
    _layout, runtime, stage_indices = _build_runtime(tmp_path, recorder, database)

    async def _failing_web_initialize() -> None:
        recorder.append("WebRegistrar.initialize")
        raise RuntimeError("web-fixture-failure")

    _replace_start_hook(
        runtime,
        stage_indices["WebRegistrar.initialize"],
        _failing_web_initialize,
    )
    try:
        with pytest.raises(RuntimeError, match="web-fixture-failure"):
            await runtime.initialize()

        assert not any(
            stage in recorder
            for stage in (
                "CacheMaintenance.start",
                "SignScheduler.start",
                "NoticesScheduler.start",
                "ClientUpdatesScheduler.start",
                "AgentToolsLifecycle.start",
            )
        )
        # 已进入的阶段按逆序释放：web 先于 login_flow。
        assert recorder.index("WebRegistrar.stop") < recorder.index(
            "LoginFlowCoordinator.stop"
        )
        assert "LoginFlowCoordinator.stop" in recorder
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_start_and_stop_hooks_are_index_aligned(tmp_path) -> None:
    """第 N 个停止动作必须对应第 N 个启动阶段，否则回滚会 stop 错对象。"""

    layout = RuntimeDataLayout(tmp_path / "plugin-data")
    database = AsyncDatabase.from_data_dir(layout.data_dir)
    runtime = build_runtime(
        _Context(),
        {},
        database=database,
        runtime_data_layout=layout,
    )
    try:
        starts = runtime.lifecycle._start_hooks
        stops = runtime.lifecycle._stop_hooks
        assert len(starts) == len(stops) == len(EXPECTED_HOOK_PAIRS)

        for index, (start, stop) in enumerate(zip(starts, stops, strict=True)):
            expected_start, expected_stop = EXPECTED_HOOK_PAIRS[index]
            assert _short_label(start, index) == expected_start, index
            assert _short_label(stop, index) == expected_stop, index
    finally:
        await database.dispose()
