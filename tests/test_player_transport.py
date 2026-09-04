"""legacy 玩家 API 到 typed contract 的边界测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.entry.event import EventActor
from src.infrastructure.http.player import DnaApiPlayerTransport, _response_data
from src.infrastructure.persistence import AsyncDatabase, CredentialRepository
from src.modules.player.contracts import PlayerFailureKind, PlayerTransportError


def _legacy_role_payload() -> dict[str, object]:
    return {
        "roleInfo": {
            "roleShow": {
                "roleChars": [
                    {
                        "charEid": "char-eid",
                        "charId": 101,
                        "elementIcon": "element://fire",
                        "gradeLevel": 6,
                        "icon": "role://101",
                        "level": 80,
                        "name": "角色甲",
                        "unLocked": True,
                    },
                ],
                "langRangeWeapons": [],
                "closeWeapons": [],
                "level": 42,
                "params": [{"paramKey": "总活跃天数", "paramValue": "99"}],
                "roleId": "role-1",
                "roleName": "测试玩家",
                "roleAchv": {"total": 3},
            },
        },
    }


def test_legacy_role_payload_maps_to_complete_typed_overview() -> None:
    overview = DnaApiPlayerTransport._overview(_legacy_role_payload())

    assert overview.role_id == "role-1"
    assert overview.role_name == "测试玩家"
    assert overview.achievement_total == 3
    assert overview.role_chars[0].char_id == 101
    assert overview.role_chars[0].char_eid == "char-eid"
    assert overview.params[0].param_value == "99"


def test_player_transport_error_redacts_server_shape_and_response_data() -> None:
    response = SimpleNamespace(is_success=False, code=500, msg="secret-token-value")

    with pytest.raises(PlayerTransportError) as raised:
        _response_data(response, resource="角色列表信息")

    error = raised.value
    assert error.kind is PlayerFailureKind.STATUS
    assert "secret-token-value" not in str(error)
    assert "secret-token-value" not in repr(error)


def test_player_transport_success_without_data_is_server_error() -> None:
    response = SimpleNamespace(is_success=True, code=0, data=None)

    with pytest.raises(PlayerTransportError) as raised:
        _response_data(response, resource="角色详情")

    assert raised.value.kind is PlayerFailureKind.SERVER


@pytest.mark.asyncio
async def test_legacy_user_preserves_target_credential_owner(tmp_path) -> None:
    """被 @ 查询时 legacy user 的身份必须与凭据所有者一致。"""

    database = AsyncDatabase(tmp_path / "player.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="target-1",
            uid="9876543210987",
            app_cookie="cookie-fixture",
            app_device_code="device-fixture",
        )

    transport = DnaApiPlayerTransport(database)
    legacy_user = await transport._legacy_user(
        EventActor("caller-1", "bot-1", "group-1"),
        "9876543210987",
        "target-1",
    )

    assert legacy_user.user_id == "target-1"
    assert legacy_user.bot_id == "bot-1"
    await database.dispose()
