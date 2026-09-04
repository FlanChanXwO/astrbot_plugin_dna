from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infrastructure.http.account import _response_error
from src.infrastructure.http.checkin import _error_kind as checkin_error_kind
from src.infrastructure.http.encyclopedia import _error_kind as encyclopedia_error_kind
from src.infrastructure.http.notices import _error_kind as notices_error_kind
from src.infrastructure.http.player import _error_kind as player_error_kind
from src.modules.account.contracts import TransportErrorKind
from src.modules.checkin.contracts import CheckinFailureKind
from src.modules.encyclopedia.contracts import EncyclopediaFailureKind
from src.modules.notices.contracts import NoticesFailureKind
from src.modules.player.contracts import PlayerFailureKind


@pytest.mark.parametrize("code", [401, 403])
def test_http_auth_status_is_classified_as_credential_failure(code):
    response = SimpleNamespace(is_success=False, code=code, msg="upstream secret")

    assert _response_error(response).kind is TransportErrorKind.CREDENTIAL
    assert checkin_error_kind(response) is CheckinFailureKind.CREDENTIAL
    assert encyclopedia_error_kind(response) is EncyclopediaFailureKind.CREDENTIAL
    assert notices_error_kind(response) is NoticesFailureKind.CREDENTIAL
    assert player_error_kind(response) is PlayerFailureKind.CREDENTIAL


def test_explicit_token_failure_is_classified_without_leaking_upstream_message():
    response = SimpleNamespace(
        is_success=False, code=200, msg="Token已失效，请重新登录"
    )
    error = _response_error(response)

    assert error.kind is TransportErrorKind.CREDENTIAL
    assert "Token已失效" not in str(error)
    assert "Token已失效" not in repr(error)
    assert checkin_error_kind(response) is CheckinFailureKind.CREDENTIAL
    assert encyclopedia_error_kind(response) is EncyclopediaFailureKind.CREDENTIAL
    assert notices_error_kind(response) is NoticesFailureKind.CREDENTIAL
    assert player_error_kind(response) is PlayerFailureKind.CREDENTIAL


def test_network_and_other_statuses_keep_their_original_categories():
    network = SimpleNamespace(is_success=False, code=-999, msg="timeout")
    server = SimpleNamespace(is_success=False, code=500, msg="server down")

    assert _response_error(network).kind is TransportErrorKind.NETWORK
    assert _response_error(server).kind is TransportErrorKind.STATUS
    assert player_error_kind(network) is PlayerFailureKind.NETWORK
    assert player_error_kind(server) is PlayerFailureKind.STATUS
