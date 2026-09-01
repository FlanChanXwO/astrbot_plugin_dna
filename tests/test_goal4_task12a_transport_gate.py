"""Goal 4 / Task 12a：所有短请求 transport 共享并发门。"""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.http.concurrency import (
    RequestConcurrencyGate,
    gated_transport_method,
)


@pytest.mark.asyncio
async def test_gated_transport_method_uses_shared_gate_and_releases() -> None:
    gate = RequestConcurrencyGate(1)
    observed: list[int] = []

    class Transport:
        request_gate = gate

        @gated_transport_method
        async def request(self, value: int) -> int:
            observed.append(value)
            await asyncio.sleep(0)
            return value

    transport = Transport()
    assert await asyncio.gather(transport.request(1), transport.request(2)) == [1, 2]
    assert observed == [1, 2]
    assert gate.active_count == 0
