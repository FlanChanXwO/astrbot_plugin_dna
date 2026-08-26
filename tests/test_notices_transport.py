"""legacy 密函/公告 API 到 typed contract 的边界、脱敏与可观测错误测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from pydantic import ValidationError

from src.entry.event import EventActor
from src.infrastructure.http.notices import DnaApiNoticesTransport, _response_data
from src.infrastructure.persistence import AsyncDatabase, CredentialRepository
from src.modules.notices.contracts import NoticesFailureKind, NoticesTransportError


def _legacy_mh_payload() -> dict[str, object]:
    return {
        "instanceInfo": [
            {
                "instances": [
                    {"id": 601, "name": "扼守"},
                    {"id": 602, "name": "拆解"},
                ],
            },
            {
                "instances": [
                    {"id": 621, "name": "勘探"},
                ],
            },
        ],
    }


def test_legacy_mh_payload_maps_to_typed_snapshot() -> None:
    snapshot = DnaApiNoticesTransport._mh_snapshot(_legacy_mh_payload())

    assert len(snapshot.sections) == 2
    role, weapon = snapshot.sections
    assert role.mh_type == "role"
    assert role.type_name == "角色"
    assert [item.name for item in role.instances] == ["扼守", "拆解"]
    assert weapon.type_name == "武器"
    assert weapon.instances[0].name == "勘探"


def test_notices_transport_error_redacts_upstream_text() -> None:
    response = SimpleNamespace(is_success=False, code=500, msg="token=secret-notice")

    with pytest.raises(NoticesTransportError) as raised:
        _response_data(response, resource="公告列表")

    error = raised.value
    assert error.kind is NoticesFailureKind.STATUS
    assert "secret-notice" not in str(error)
    assert "secret-notice" not in repr(error)


def test_ann_list_payload_maps_posts_with_pure_legacy_helpers() -> None:
    transport = DnaApiNoticesTransport.__new__(DnaApiNoticesTransport)
    posts = [
        {
            "postId": "1001",
            "postTitle": "版本更新公告",
            "showTime": "2026-08-01",
            "postCover": "https://cdn.test/cover.png",
        },
        {
            "postId": "1002",
            "postTitle": "",
            "postContent": "活动预告内容很长很长很长很长很长很长很长很长很长",
            "postTime": "2026-08-02",
        },
    ]
    snapshot = transport._ann_snapshot(posts)

    assert len(snapshot.posts) == 2
    first, second = snapshot.posts
    assert first.post_id == "1001"
    assert first.title == "版本更新公告"
    assert first.time == "2026-08-01"
    assert first.preview == "https://cdn.test/cover.png"
    assert second.title.startswith("活动预告内容")
    assert second.time == "2026-08-02"


def test_mh_missing_instance_info_is_observable_structure_error() -> None:
    """密函页面结构变化（缺 instanceInfo）必须显式失败，不伪造空成功。"""

    with pytest.raises(ValidationError):
        DnaApiNoticesTransport._mh_snapshot({"roleInfo": {}})


def test_ann_detail_non_list_content_is_observable_structure_error() -> None:
    """公告详情结构变化（postContent 非列表）必须显式失败。"""

    data = {"postId": "1001", "postContent": {"weird": 1}}

    with pytest.raises((AttributeError, KeyError, TypeError)):
        DnaApiNoticesTransport._ann_detail(data, "1001")


async def _transport_with_credential(tmp_path: Path) -> tuple[DnaApiNoticesTransport, AsyncDatabase]:
    database = AsyncDatabase(tmp_path / "notices.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await CredentialRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1234567890123",
            app_cookie="cookie-secret-999",
            app_device_code="dev-secret-001",
            app_d_num="",
            app_refresh_token="",
            app_status="",
            web_token="",
            web_device_code="",
            web_d_num="",
            web_refresh_token="",
            web_status="",
        )
    return DnaApiNoticesTransport(database), database


def _patch_dna_api(monkeypatch, fake) -> None:
    from src.utils import dna_api

    monkeypatch.setattr(dna_api, "get_default_role_for_tool", fake)


@pytest.mark.asyncio
async def test_get_mh_network_failure_is_observable_and_redacted(tmp_path, monkeypatch) -> None:
    """网络失败映射为 NETWORK 错误，凭据/异常原文不进异常。"""

    transport, database = await _transport_with_credential(tmp_path)
    try:
        def boom(*_args, **_kwargs):
            raise aiohttp.ClientError("connection refused token=secret-mh")

        _patch_dna_api(monkeypatch, boom)
        with pytest.raises(NoticesTransportError) as raised:
            await transport.get_mh(
                EventActor("user-1", "bot-1", "group-1"),
                "1234567890123",
                credential_user_id="user-1",
            )
        error = raised.value
        assert error.kind is NoticesFailureKind.NETWORK
        assert "secret-mh" not in str(error)
        assert "secret-mh" not in repr(error)
        assert "cookie-secret-999" not in str(error)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_get_mh_status_error_does_not_fabricate_success(tmp_path, monkeypatch) -> None:
    """服务端返回失败状态必须抛错，不把 msg 原文带进异常。"""

    transport, database = await _transport_with_credential(tmp_path)
    try:
        def failing(*_args, **_kwargs):
            return SimpleNamespace(is_success=False, code=403, msg="token=secret-forbidden")

        async def failing_async(*_args, **_kwargs):
            return failing()

        _patch_dna_api(monkeypatch, failing_async)
        with pytest.raises(NoticesTransportError) as raised:
            await transport.get_mh(
                EventActor("user-1", "bot-1", "group-1"),
                "1234567890123",
                credential_user_id="user-1",
            )
        error = raised.value
        assert error.kind is NoticesFailureKind.STATUS
        assert "secret-forbidden" not in str(error)
        assert "secret-forbidden" not in repr(error)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_get_mh_structure_change_is_server_error(tmp_path, monkeypatch) -> None:
    """成功响应但密函结构变化映射为 SERVER 错误，不伪造成功。"""

    transport, database = await _transport_with_credential(tmp_path)
    try:
        def ok_but_empty(*_args, **_kwargs):
            return SimpleNamespace(is_success=True, code=0, data={"roleInfo": {}})

        async def ok_but_empty_async(*_args, **_kwargs):
            return ok_but_empty()

        _patch_dna_api(monkeypatch, ok_but_empty_async)
        with pytest.raises(NoticesTransportError) as raised:
            await transport.get_mh(
                EventActor("user-1", "bot-1", "group-1"),
                "1234567890123",
                credential_user_id="user-1",
            )
        assert raised.value.kind is NoticesFailureKind.SERVER
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_get_mh_any_falls_back_to_next_valid_credential(tmp_path: Path, monkeypatch) -> None:
    """当首个凭据失效或报错时，get_mh_any 自动回退尝试后续有效凭据并成功返回。"""

    database = AsyncDatabase(tmp_path / "notices_multi.sqlite3")
    await database.create_schema_for_tests()
    from src.infrastructure.persistence import AccountBindingRepository
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1000000000001",
            is_active=True,
        )
        await AccountBindingRepository.add(
            session,
            user_id="user-2",
            bot_id="bot-1",
            uid="1000000000002",
            is_active=True,
        )
        # 添加两个账号凭据：user-1 会失败，user-2 会成功
        await CredentialRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            uid="1000000000001",
            app_cookie="cookie-1",
            app_device_code="dev-1",
            app_d_num="",
            app_refresh_token="",
            app_status="",
            web_token="",
            web_device_code="",
            web_d_num="",
            web_refresh_token="",
            web_status="",
        )
        await CredentialRepository.add(
            session,
            user_id="user-2",
            bot_id="bot-1",
            uid="1000000000002",
            app_cookie="cookie-2",
            app_device_code="dev-2",
            app_d_num="",
            app_refresh_token="",
            app_status="",
            web_token="",
            web_device_code="",
            web_d_num="",
            web_refresh_token="",
            web_status="",
        )

    transport = DnaApiNoticesTransport(database)

    try:
        async def fake_get_default_role(user):
            # user-1 模拟服务端返回错误（例如 userId 为空或凭据过期）
            if getattr(user, "user_id", "") == "user-1":
                return SimpleNamespace(is_success=False, code=220, msg="userId不能为空")
            # user-2 成功返回有效密函数据
            return SimpleNamespace(
                is_success=True,
                code=200,
                data=_legacy_mh_payload(),
            )

        _patch_dna_api(monkeypatch, fake_get_default_role)

        snapshot = await transport.get_mh_any()
        assert len(snapshot.sections) == 2
        assert snapshot.sections[0].type_name == "角色"
        assert [item.name for item in snapshot.sections[0].instances] == ["扼守", "拆解"]
    finally:
        await database.dispose()
