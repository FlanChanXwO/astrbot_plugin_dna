"""Goal 4 / Task 10：全局短请求并发门契约。"""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.config.settings import DnabySettings
from src.infrastructure.http.concurrency import RequestConcurrencyGate


@pytest.mark.asyncio
async def test_gate_caps_short_requests_and_releases_after_success() -> None:
    gate = RequestConcurrencyGate(2)
    active = 0
    peak = 0

    async def operation() -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return peak

    results = await asyncio.gather(*(gate.run(operation) for _ in range(8)))

    assert max(results) == 2
    assert gate.active_count == 0


@pytest.mark.asyncio
async def test_gate_single_flight_shares_result_and_cleans_up_on_failure() -> None:
    gate = RequestConcurrencyGate(4)
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "shared"

    assert (
        await asyncio.gather(*(gate.run(operation, key="same-key") for _ in range(5)))
        == ["shared"] * 5
    )
    assert calls == 1

    async def fail() -> None:
        raise RuntimeError("temporary")

    with pytest.raises(RuntimeError, match="temporary"):
        await gate.run(fail, key="retry-key")
    with pytest.raises(RuntimeError, match="temporary"):
        await gate.run(fail, key="retry-key")
    assert gate.in_flight_count == 0


@pytest.mark.asyncio
async def test_gate_cancellation_releases_slot_and_allows_retry() -> None:
    gate = RequestConcurrencyGate(1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> None:
        started.set()
        await release.wait()

    task = asyncio.create_task(gate.run(blocked))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.active_count == 0

    assert await gate.run(lambda: asyncio.sleep(0, result="ok")) == "ok"


def test_network_settings_expose_positive_request_limit() -> None:
    settings = DnabySettings.from_config({})
    assert settings.network.max_concurrent_requests == 4
    with pytest.raises(ValueError):
        DnabySettings.from_config({"network": {"max_concurrent_requests": 0}})


def test_gate_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="大于等于 1"):
        RequestConcurrencyGate(0)
    with pytest.raises(ValueError, match="大于等于 1"):
        RequestConcurrencyGate(True)  # type: ignore[arg-type]


def test_bootstrap_builds_one_configured_gate_and_injects_transports(tmp_path) -> None:
    from types import SimpleNamespace

    from src.bootstrap import build_runtime
    from src.infrastructure.http import RequestConcurrencyGate
    from src.infrastructure.persistence import AsyncDatabase

    database = AsyncDatabase(tmp_path / "runtime.sqlite3")
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {"network": {"max_concurrent_requests": 3}},
        database=database,
    )
    gate = runtime.services["request_gate"]
    assert isinstance(gate, RequestConcurrencyGate)
    assert gate.limit == 3
    assert runtime.services["player_service"].transport.request_gate is gate
    assert runtime.services["checkin_service"].transport.request_gate is gate
    assert runtime.services["encyclopedia_service"].transport.request_gate is gate
    assert runtime.services["notices_service"].transport.request_gate is gate
