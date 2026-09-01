"""Goal 2 / Task 04：跨 Bot 消费者与 legacy transport 的全局身份契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.entry.event import EventActor
from src.entry.response import ImageResponse
from src.infrastructure.http.checkin import DnaApiCheckinTransport
from src.infrastructure.http.encyclopedia import DnaApiEncyclopediaTransport
from src.infrastructure.http.notices import DnaApiNoticesTransport
from src.infrastructure.http.player import DnaApiPlayerTransport
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.checkin.contracts import CheckinCommandRequest, SignCalendar
from src.modules.checkin.service import CheckinService
from src.modules.encyclopedia.contracts import EncyclopediaRequest, PlayerShortNote
from src.modules.encyclopedia.service import EncyclopediaService
from src.modules.notices.contracts import MhSnapshot
from src.modules.player.contracts import PlayerCommandRequest, RoleOverview
from src.modules.player.service import PlayerService
from src.modules.privacy import PrivacyService

UID = "1234567890123"


async def _database(tmp_path: Path) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "task04.sqlite3")
    await database.create_schema_for_tests()
    return database


async def _add_binding_and_credential(
    database: AsyncDatabase,
    *,
    user_id: str = "user-1",
    uid: str = UID,
    cookie: str = "cookie-task04",
) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            group_id="group-1",
            is_active=True,
        )
        await CredentialRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            app_cookie=cookie,
        )


class _PlayerTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_overview(self, actor, uid, *, credential_user_id):
        self.calls.append((actor.bot_id, uid, credential_user_id))
        return RoleOverview(role_id="role-1", role_name="全局玩家")


class _PlayerRenderer:
    def __init__(self, path: Path) -> None:
        self.path = path

    def render_overview(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(path=self.path, sidecar=None, manifest=None)


@pytest.mark.asyncio
async def test_player_service_reads_global_binding_from_another_bot(tmp_path: Path) -> None:
    """玩家命令从第二个 Bot 触发时仍读取同一全局绑定。"""

    database = await _database(tmp_path)
    await _add_binding_and_credential(database)
    transport = _PlayerTransport()
    service = PlayerService(
        database,
        cast(Any, transport),
        PrivacyService(database),
        cast(Any, _PlayerRenderer(tmp_path / "player.png")),
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-2", "group-2"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.image == str(tmp_path / "player.png")
    assert transport.calls == [("bot-2", UID, "user-1")]
    await database.dispose()


class _EncyclopediaTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_short_note(self, actor, uid, *, credential_user_id):
        self.calls.append((actor.bot_id, uid, credential_user_id))
        return PlayerShortNote()


class _EncyclopediaRenderer:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def render_stamina(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(path=self.path, sidecar=None, manifest=None)


@pytest.mark.asyncio
async def test_encyclopedia_service_reads_global_binding_from_another_bot(tmp_path: Path) -> None:
    """百科命令从第二个 Bot 触发时仍读取同一全局绑定。"""

    database = await _database(tmp_path)
    await _add_binding_and_credential(database)
    transport = _EncyclopediaTransport()
    service = EncyclopediaService(
        database,
        cast(Any, transport),
        PrivacyService(database),
        cast(Any, _EncyclopediaRenderer(tmp_path / "stamina.png")),
        EncyclopediaResourceStore(),
    )

    response = await service.stamina(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-2", "group-2"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.image == str(tmp_path / "stamina.png")
    assert transport.calls == [("bot-2", UID, "user-1")]
    await database.dispose()


class _CheckinTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_sign_calendar(self, actor, uid, *, credential_user_id):
        self.calls.append((actor.bot_id, uid, credential_user_id))
        return SignCalendar(today_signed=True)


@pytest.mark.asyncio
async def test_checkin_service_reads_global_binding_from_another_bot(tmp_path: Path) -> None:
    """签到命令从第二个 Bot 触发时仍使用全局账号凭据。"""

    database = await _database(tmp_path)
    await _add_binding_and_credential(database)
    transport = _CheckinTransport()
    service = CheckinService(
        database,
        cast(Any, transport),
        PrivacyService(database),
        cast(Any, object()),
        community_tasks=(),
    )

    response = await service.manual_sign(
        CheckinCommandRequest(
            actor=EventActor("user-1", "bot-2", "group-2"),
            target_user_id=None,
        ),
    )

    assert "请勿重复签到" in response.text
    assert transport.calls == [("bot-2", UID, "user-1")]
    await database.dispose()


@pytest.mark.asyncio
async def test_auto_checkin_iterates_each_global_binding_once(tmp_path: Path) -> None:
    """自动签到不按旧 Bot 分组，且每个全局 UID 只处理一次。"""

    database = await _database(tmp_path)
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1000000000001",
            group_id="group-1",
            is_active=False,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1000000000002",
            group_id="group-2",
            is_active=True,
        )
    transport = _CheckinTransport()
    service = CheckinService(
        database,
        cast(Any, transport),
        PrivacyService(database),
        cast(Any, object()),
        community_tasks=(),
        concurrency=2,
    )

    summary = await service._run_all_signs()

    assert summary.success == 2
    assert summary.failed == 0
    assert [(uid, owner) for _bot, uid, owner in transport.calls] == [
        ("1000000000001", "user-1"),
        ("1000000000002", "user-1"),
    ]
    assert all(bot_id for bot_id, _uid, _owner in transport.calls)
    await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_type",
    (
        DnaApiPlayerTransport,
        DnaApiEncyclopediaTransport,
        DnaApiCheckinTransport,
        DnaApiNoticesTransport,
    ),
)
async def test_api_transports_use_global_credentials_and_keep_event_bot_context(
    tmp_path: Path,
    transport_type: type[Any],
) -> None:
    """四个 API transport 全局查凭据，同时把事件 Bot ID 留给 legacy DNAUser。"""

    database = await _database(tmp_path)
    await _add_binding_and_credential(database)
    transport = transport_type(database)

    user = await transport._legacy_user(
        EventActor("user-1", "bot-2", "group-2"),
        UID,
        "user-1",
    )

    assert user.user_id == "user-1"
    assert user.uid == UID
    assert user.cookie == "cookie-task04"
    assert user.bot_id == "bot-2"
    await database.dispose()


def _legacy_mh_payload() -> dict[str, object]:
    return {
        "instanceInfo": [
            {
                "mhType": "role",
                "instances": [{"id": 601, "name": "扼守"}],
            },
        ],
    }


@pytest.mark.asyncio
async def test_notices_get_mh_any_falls_back_across_global_bindings(tmp_path: Path, monkeypatch) -> None:
    """计划任务的密函读取遍历全局凭据，不依赖已删除的 binding.bot_id。"""

    database = await _database(tmp_path)
    async with database.transaction() as session:
        for index, user_id in enumerate(("user-1", "user-2"), start=1):
            uid = f"100000000000{index}"
            await AccountBindingRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                is_active=True,
            )
            await CredentialRepository.add(
                session,
                user_id=user_id,
                uid=uid,
                app_cookie=f"cookie-{user_id}",
            )

    seen: list[tuple[str, str, str]] = []

    async def fake_get_default_role(user) -> SimpleNamespace:
        seen.append((user.user_id, user.uid, user.bot_id))
        if user.user_id == "user-1":
            return SimpleNamespace(is_success=False, code=401, data=None)
        return SimpleNamespace(is_success=True, code=200, data=_legacy_mh_payload())

    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_default_role_for_tool", fake_get_default_role)
    snapshot = await DnaApiNoticesTransport(database).get_mh_any()

    assert isinstance(snapshot, MhSnapshot)
    assert [user_id for user_id, _uid, _bot_id in seen] == ["user-1", "user-2"]
    assert all(bot_id for _user_id, _uid, bot_id in seen)
    assert snapshot.sections[0].instances[0].name == "扼守"
    await database.dispose()
