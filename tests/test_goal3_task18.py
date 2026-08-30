"""Goal 3 Task 18：兑换码新契约与别名写能力移除。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import aiohttp
import pytest

from src.entry.commands import load_command_registry
from src.infrastructure.http import encyclopedia as encyclopedia_http
from src.infrastructure.http.encyclopedia import (
    DEFAULT_CODE_URL,
    DnaApiEncyclopediaTransport,
)
from src.modules.encyclopedia import messages
from src.modules.encyclopedia.contracts import CodeEntry, EncyclopediaTransportError

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=SHANGHAI)
RESOURCE_RAW_URL = (
    "https://raw.githubusercontent.com/FlanChanXwO/"
    "astrbot_plugin_dna_resources/main/data/redeem_codes.json"
)


def _actor():
    from src.entry.event import EventActor

    return EventActor("user-1", "bot-1", "group-1")


def _payload(*entries: dict[str, object]) -> dict[str, object]:
    return {"format_version": 1, "data": list(entries)}


class _FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    async def text(self) -> str:
        return json.dumps(self.payload)


class _FakeSession:
    def __init__(self, response: _FakeResponse | None, calls: list[str]) -> None:
        self.response = response
        self.calls = calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        if self.response is None:
            raise aiohttp.ClientConnectionError("provider unavailable")
        return self.response


def test_code_entry_exposes_all_optional_resource_fields() -> None:
    entry = CodeEntry(
        code="CODE-FULL",
        reward="委托密函×3",
        valid_from=NOW,
        expires_at=datetime(2026, 9, 1, 0, 0, tzinfo=SHANGHAI),
        platforms=("pc", "android", "ios"),
        servers=("cn", "global"),
    )

    assert entry.reward == "委托密函×3"
    assert entry.valid_from == NOW
    assert entry.platforms == ("pc", "android", "ios")
    assert entry.servers == ("cn", "global")


def test_codes_parse_resource_contract_and_filter_status_by_timezone() -> None:
    snapshot = DnaApiEncyclopediaTransport._codes(
        _payload(
            {
                "code": " planned ",
                "valid_from": "2026-08-20T12:00:01+08:00",
            },
            {
                "code": "CURRENT-NO-END",
                "valid_from": "2026-08-20T12:00:00+08:00",
                "reward": "无截止奖励",
            },
            {
                "code": "CURRENT-FULL",
                "reward": "委托密函×3",
                "valid_from": "2026-08-01T00:00:00+08:00",
                "expires_at": "2026-09-01T00:00:00+08:00",
                "platforms": ["pc", "android"],
                "servers": ["cn"],
            },
            {
                "code": "EXPIRED",
                "expires_at": "2026-08-20T12:00:00+08:00",
            },
        ),
        now=NOW,
    )

    assert snapshot.codes == ("CURRENT-NO-END", "CURRENT-FULL")
    assert snapshot.entries[0] == CodeEntry(
        code="CURRENT-NO-END",
        reward="无截止奖励",
        valid_from=NOW,
    )
    assert snapshot.entries[1] == CodeEntry(
        code="CURRENT-FULL",
        reward="委托密函×3",
        valid_from=datetime(2026, 8, 1, 0, 0, tzinfo=SHANGHAI),
        expires_at=datetime(2026, 9, 1, 0, 0, tzinfo=SHANGHAI),
        platforms=("pc", "android"),
        servers=("cn",),
    )


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"format_version": 2, "data": []},
        _payload({"code": "CODE", "unknown": "field"}),
        _payload({"code": "CODE", "valid_from": "2026-08-20T12:00:00"}),
        _payload({"code": "CODE", "platforms": ["desktop"]}),
        _payload({"code": "CODE"}, {"code": " CODE "}),
    ),
)
@pytest.mark.asyncio
async def test_code_contract_errors_are_distinct_and_detail_safe(
    payload: dict[str, object],
) -> None:
    transport = DnaApiEncyclopediaTransport(object(), code_provider=lambda _actor: payload)

    with pytest.raises(EncyclopediaTransportError) as raised:
        await transport.get_codes(_actor())

    assert raised.value.kind.value == "contract"
    assert "unknown" not in str(raised.value)


@pytest.mark.asyncio
async def test_default_code_provider_uses_resource_raw_url_and_acceleration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    session = _FakeSession(_FakeResponse(200, _payload()), calls)
    monkeypatch.setattr(encyclopedia_http.aiohttp, "ClientSession", lambda: session)

    transport = DnaApiEncyclopediaTransport(
        object(),
        acceleration_prefix="https://mirror.example/gh",
    )
    snapshot = await transport.get_codes(_actor())

    assert DEFAULT_CODE_URL == RESOURCE_RAW_URL
    assert calls == [f"https://mirror.example/gh/{RESOURCE_RAW_URL}"]
    assert "gitcode" not in calls[0]
    assert snapshot.codes == ()


@pytest.mark.asyncio
async def test_code_provider_status_and_network_errors_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_calls: list[str] = []
    status_session = _FakeSession(_FakeResponse(503, {}), status_calls)
    monkeypatch.setattr(encyclopedia_http.aiohttp, "ClientSession", lambda: status_session)
    transport = DnaApiEncyclopediaTransport(object())

    with pytest.raises(EncyclopediaTransportError) as status_error:
        await transport.get_codes(_actor())
    assert status_error.value.kind.value == "status"

    network_calls: list[str] = []
    network_session = _FakeSession(None, network_calls)
    monkeypatch.setattr(encyclopedia_http.aiohttp, "ClientSession", lambda: network_session)

    with pytest.raises(EncyclopediaTransportError) as network_error:
        await transport.get_codes(_actor())
    assert network_error.value.kind.value == "network"


def test_code_entry_message_shows_present_fields_without_empty_labels() -> None:
    full_text = messages.code_entry(
        CodeEntry(
            code="CODE-FULL",
            reward="委托密函×3",
            valid_from=NOW,
            expires_at=datetime(2026, 9, 1, 0, 0, tzinfo=SHANGHAI),
            platforms=("pc", "ios"),
            servers=("cn", "global"),
        ),
    )
    minimal_text = messages.code_entry(CodeEntry(code="CODE-MIN"))

    assert full_text.splitlines() == [
        "CODE-FULL",
        "奖励：委托密函×3",
        "生效时间：2026-08-20 12:00:00",
        "有效期至：2026-09-01 00:00:00",
        "平台：pc、ios",
        "区服：cn、global",
    ]
    assert minimal_text == "CODE-MIN"
    assert "奖励：" not in minimal_text
    assert "生效时间：" not in minimal_text
    assert "有效期至：" not in minimal_text
    assert "平台：" not in minimal_text
    assert "区服：" not in minimal_text


def test_alias_write_capability_and_all_projections_are_removed() -> None:
    specs = {spec.id: spec for spec in load_command_registry()}
    assert len(specs) == 61
    assert "alias_list" in specs
    assert "alias_all_list" in specs
    assert "alias_add_delete" not in specs
    assert "alias_recover" not in specs

    manifest = json.loads((ROOT / "commands.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in manifest} >= {"alias_list", "alias_all_list"}
    assert {item["id"] for item in manifest}.isdisjoint(
        {"alias_add_delete", "alias_recover"}
    )

    help_data = json.loads((ROOT / "src/resources/help/help.json").read_text(encoding="utf-8"))
    help_text = json.dumps(help_data, ensure_ascii=False)
    assert "添加/删除角色别名" not in help_text
    assert "添加/删除武器别名" not in help_text
    assert "恢复别名" not in help_text

    assert not (ROOT / "src/modules/operations/alias_service.py").exists()
    assert not (ROOT / "src/modules/encyclopedia/alias_ops.py").exists()

    docs = (ROOT / "docs/usage/commands.md").read_text(encoding="utf-8")
    assert "别名" in docs
    for phrase in ("添加角色别名", "删除角色别名", "添加/删除角色别名", "恢复别名"):
        assert phrase not in docs


def test_panel_custom_commands_remain_projected() -> None:
    specs = {spec.id for spec in load_command_registry()}
    assert {
        "upload_panel_img",
        "list_panel_imgs",
        "delete_panel_img_by_id",
        "delete_all_panel_imgs",
        "delete_original_panel_img",
        "compress_panel_imgs",
        "resource_status",
    } <= specs
    bootstrap = (ROOT / "src/bootstrap.py").read_text(encoding="utf-8")
    assert 'runtime_database.path.parent / "panel_custom"' in bootstrap
