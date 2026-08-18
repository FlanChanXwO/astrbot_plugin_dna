"""legacy 签到 API 到 typed contract 的边界测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infrastructure.http.checkin import DnaApiCheckinTransport, _response_data
from src.modules.checkin.contracts import (
    CheckinFailureKind,
    CheckinTransportError,
    SignStatus,
)


def _legacy_calendar_payload() -> dict[str, object]:
    return {
        "todaySignin": False,
        "userGoldNum": 123,
        "dayAward": [
            {
                "gameId": 1,
                "periodId": 9,
                "iconUrl": "icon://award-1",
                "id": 1,
                "dayInPeriod": 4,
                "updateTime": 0,
                "awardNum": 5,
                "thirdProductId": "p-1",
                "createTime": 0,
                "awardName": "武器经验",
            },
        ],
        "signinTime": 3,
        "period": {
            "gameId": 1,
            "retryCos": 0,
            "endDate": 0,
            "id": 9,
            "startDate": 0,
            "retryTimes": 0,
            "overDays": 7,
            "createTime": 0,
            "name": "周期甲",
        },
        "roleInfo": {
            "headUrl": "head://1",
            "roleId": "101",
            "roleName": "角色甲",
            "level": 60,
            "roleBoundId": "bound-1",
        },
    }


def test_legacy_calendar_payload_maps_to_typed_sign_calendar() -> None:
    calendar = DnaApiCheckinTransport._sign_calendar(_legacy_calendar_payload())

    assert calendar.today_signed is False
    assert calendar.user_gold == 123
    assert calendar.signin_time == 3
    assert calendar.day_awards[0].award_name == "武器经验"
    assert calendar.day_awards[0].award_num == 5
    assert calendar.period is not None
    assert calendar.period.over_days == 7
    assert calendar.role_info is not None
    assert calendar.role_info.role_name == "角色甲"


def test_legacy_calendar_payload_allows_missing_today_state() -> None:
    """未签到时后端精简返回，today_signed/signin_time/user_gold 允许缺失。"""

    payload = _legacy_calendar_payload()
    payload.pop("todaySignin")
    payload.pop("signinTime")
    payload.pop("userGoldNum")
    payload.pop("roleInfo")

    calendar = DnaApiCheckinTransport._sign_calendar(payload)

    assert calendar.today_signed is None
    assert calendar.signin_time is None
    assert calendar.user_gold is None
    assert calendar.role_info is None


def test_checkin_transport_error_redacts_upstream_text() -> None:
    response = SimpleNamespace(is_success=False, code=500, msg="token=secret-checkin")

    with pytest.raises(CheckinTransportError) as raised:
        _response_data(response, resource="签到日历")

    error = raised.value
    assert error.kind is CheckinFailureKind.STATUS
    assert "secret-checkin" not in str(error)
    assert "secret-checkin" not in repr(error)


def test_game_sign_maps_already_signed_code_to_skip() -> None:
    """游戏签到 code 711 映射为 SKIP，不是伪造成功。"""

    response = SimpleNamespace(is_success=False, code=711, data=None)

    assert DnaApiCheckinTransport._game_sign_status(response) is SignStatus.SKIP


def test_game_sign_maps_success_to_done() -> None:
    assert (
        DnaApiCheckinTransport._game_sign_status(SimpleNamespace(is_success=True, code=0))
        is SignStatus.DONE
    )
    assert (
        DnaApiCheckinTransport._game_sign_status(SimpleNamespace(is_success=False, code=500))
        is SignStatus.FAILED
    )


def test_bbs_sign_maps_code_10000_to_done() -> None:
    assert (
        DnaApiCheckinTransport._bbs_sign_status(SimpleNamespace(is_success=False, code=10000))
        is SignStatus.DONE
    )
    assert (
        DnaApiCheckinTransport._bbs_sign_status(SimpleNamespace(is_success=False, code=500))
        is SignStatus.FAILED
    )
