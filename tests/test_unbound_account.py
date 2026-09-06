from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.entry.event import EventActor
from src.entry.response import PlainTextResponse
from src.infrastructure.persistence import AsyncDatabase
from src.modules.checkin.contracts import CheckinCommandRequest
from src.modules.checkin.service import CheckinService
from src.modules.encyclopedia.contracts import EncyclopediaRequest
from src.modules.encyclopedia.service import EncyclopediaService
from src.modules.player.contracts import PlayerCommandRequest
from src.modules.player.service import PlayerService
from src.modules.privacy import PrivacyService


@dataclass(frozen=True)
class _UnboundCase:
    operation: str
    invoke: Callable[[str | None], Awaitable[PlainTextResponse]]


async def _empty_database(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "unbound.sqlite3")
    await database.create_schema_for_tests()
    return database


def _actor() -> EventActor:
    return EventActor("user-1", "bot-1", "group-1")


def _cases(database: AsyncDatabase) -> tuple[_UnboundCase, ...]:
    privacy = PrivacyService(database)
    encyclopedia = EncyclopediaService(
        database,
        object(),
        privacy,
        object(),
        object(),
    )
    checkin = CheckinService(database, object(), privacy, object())
    player = PlayerService(database, object(), privacy, object())
    async def encyclopedia_case(target_user_id: str | None) -> PlainTextResponse:
        response = await encyclopedia.stamina(
            EncyclopediaRequest(actor=_actor(), target_user_id=target_user_id)
        )
        assert isinstance(response, PlainTextResponse)
        return response

    async def checkin_case(target_user_id: str | None) -> PlainTextResponse:
        response = await checkin.manual_sign(
            CheckinCommandRequest(
                actor=_actor(),
                target_user_id=target_user_id,
                text="签到",
            )
        )
        assert isinstance(response, PlainTextResponse)
        return response

    async def player_case(target_user_id: str | None) -> PlainTextResponse:
        response = await player.role_overview(
            PlayerCommandRequest(actor=_actor(), target_user_id=target_user_id)
        )
        assert isinstance(response, PlainTextResponse)
        return response

    return (
        _UnboundCase("stamina", encyclopedia_case),
        _UnboundCase("manual_sign", checkin_case),
        _UnboundCase("role_overview", player_case),
    )


@pytest.mark.asyncio
async def test_unbound_self_uses_dedicated_tip_and_safe_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = await _empty_database(tmp_path)
    caplog.set_level(logging.WARNING)

    try:
        for case in _cases(database):
            caplog.clear()
            response = await case.invoke(None)

            assert response.text == "当前未绑定账号，请先登录"
            log_text = "\n".join(record.getMessage() for record in caplog.records)
            assert (
                f"账号绑定缺失 operation={case.operation} "
                "scope=self reason=local_binding_missing"
            ) in log_text
            assert "当前未绑定账号，请先登录" not in log_text
            assert "token" not in log_text.lower()
            assert "cookie" not in log_text.lower()
            assert "https://" not in log_text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_unbound_target_uses_dedicated_tip_and_safe_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = await _empty_database(tmp_path)
    caplog.set_level(logging.WARNING)

    try:
        for case in _cases(database):
            caplog.clear()
            response = await case.invoke("user-2")

            assert response.text == "目标用户尚未绑定账号，无法查询"
            log_text = "\n".join(record.getMessage() for record in caplog.records)
            assert (
                f"账号绑定缺失 operation={case.operation} "
                "scope=target reason=local_binding_missing"
            ) in log_text
            assert "目标用户尚未绑定账号，无法查询" not in log_text
            assert "token" not in log_text.lower()
            assert "cookie" not in log_text.lower()
            assert "https://" not in log_text
    finally:
        await database.dispose()
