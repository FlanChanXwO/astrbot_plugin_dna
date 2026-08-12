"""legacy 密函/公告 API 到 typed contract 的边界测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infrastructure.http.notices import DnaApiNoticesTransport, _response_data
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
