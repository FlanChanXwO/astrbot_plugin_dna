"""Goal 2 / D02：用真实 PlayerRenderer 链路核对管理员预览契约。"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from PIL import Image

import src.infrastructure.rendering.player as player_rendering
from src.entry.event import EventActor
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import (
    HtmlRenderer,
    PlayerRenderer,
    RenderedPlayerImage,
    ResourceMap,
)
from src.modules.admin import AdminPreviewRequest, AdminPreviewService
from src.modules.player.contracts import (
    AttributeBag,
    DamageCalculation,
    DamageSnapshot,
    DamageValues,
    RoleAttribute,
    RoleDetail,
    RoleItem,
    RoleOverview,
)
from src.modules.privacy import PrivacyService


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为 D02 真实渲染链路提供隔离数据库。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="player-1",
            uid="1001",
            group_id="group-1",
            is_active=True,
        )
    try:
        yield database
    finally:
        await database.dispose()


def _overview() -> RoleOverview:
    return RoleOverview(
        role_id="1001",
        role_name="真实渲染玩家",
        level=42,
        role_chars=[
            RoleItem(
                char_id=101,
                char_eid="char-eid-101",
                name="角色甲",
                unlocked=True,
            ),
        ],
    )


def _detail() -> RoleDetail:
    return RoleDetail(
        attribute=RoleAttribute(),
        char_id=101,
        char_name="角色甲",
        level=80,
    )


def _damage() -> DamageCalculation:
    return DamageCalculation.success(
        DamageSnapshot(
            damage=DamageValues(),
            final_attribute=AttributeBag(),
            base_attribute=AttributeBag(),
        ),
    )


class _Transport:
    """只提供管理员预览真实链路所需的 typed player transport。"""

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        assert actor.user_id == "dashboard-admin"
        assert uid == "1001"
        assert credential_user_id == "player-1"
        return _overview()

    async def get_role_detail(
        self,
        actor: EventActor,
        uid: str,
        char_id: int,
        char_eid: str,
        *,
        credential_user_id: str,
    ) -> RoleDetail:
        assert actor.user_id == "dashboard-admin"
        assert uid == "1001"
        assert char_id == 101
        assert char_eid == "char-eid-101"
        assert credential_user_id == "player-1"
        return _detail()

    async def calculate_damage(
        self,
        actor: EventActor,
        uid: str,
        role_detail: RoleDetail,
        con_weapon: Any,
        close_weapon: Any,
        ranged_weapon: Any,
        *,
        credential_user_id: str,
    ) -> DamageCalculation:
        assert actor.user_id == "dashboard-admin"
        assert uid == "1001"
        assert role_detail.char_id == 101
        assert con_weapon is None
        assert close_weapon is None
        assert ranged_weapon is None
        assert credential_user_id == "player-1"
        return _damage()


class _ValidJpegT2I:
    """以合法 JPEG 响应替代外部 T2I，保留 HtmlRenderer 的真实校验。"""

    def __init__(self) -> None:
        self.templates: list[str] = []

    async def render_custom_template(
        self,
        tmpl_str: str,
        tmpl_data: dict[str, Any],
        return_url: bool = False,
        options: dict[str, object] | None = None,
    ) -> bytes:
        del tmpl_data, return_url, options
        self.templates.append(tmpl_str)
        output = BytesIO()
        Image.new("RGB", (7, 5), "#234").save(output, format="JPEG")
        return output.getvalue()


@pytest.mark.asyncio
async def test_admin_preview_uses_real_player_renderer_contract(
    database: AsyncDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理员预览必须经过真实模板/HtmlRenderer/PlayerRenderer 链路。"""

    t2i = _ValidJpegT2I()
    monkeypatch.setattr(
        player_rendering,
        "_RENDERER",
        HtmlRenderer(t2i=t2i),
    )

    async def fake_image(*args: Any, **kwargs: Any) -> Image.Image:
        del args, kwargs
        return Image.new("RGBA", (64, 64), "white")

    async def fake_header(*args: Any, **kwargs: Any) -> dict[str, object]:
        del args, kwargs
        return {
            "avatar": "data:image/png;base64,AA==",
            "avatar_frame": "data:image/png;base64,AA==",
            "level": 42,
            "level_background": "data:image/png;base64,AA==",
            "name": "真实渲染玩家",
            "stats": [],
            "stats_background": "data:image/png;base64,AA==",
            "uid": "1001",
        }

    monkeypatch.setattr(player_rendering, "build_profile_header", fake_header)
    monkeypatch.setattr(player_rendering, "get_avatar_img", fake_image)
    monkeypatch.setattr(player_rendering, "get_attr_img", fake_image)
    monkeypatch.setattr(player_rendering, "get_paint_img", fake_image)
    monkeypatch.setattr(player_rendering, "get_role_panel_img", lambda *_: None)

    async def fail_privacy(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("admin preview 不得调用 PrivacyService")

    monkeypatch.setattr(PrivacyService, "resolve_query", fail_privacy)

    service = AdminPreviewService(
        database,
        cast(Any, _Transport()),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )
    actor = EventActor("dashboard-admin", "bot-9", "group-9")

    overview = await service.preview_overview(
        AdminPreviewRequest(actor=actor, user_id="player-1", uid="1001"),
    )
    detail = await service.preview_detail(
        AdminPreviewRequest(
            actor=actor,
            user_id="player-1",
            uid="1001",
            char_name="角色甲",
        ),
    )

    assert overview.ok is True
    assert detail.ok is True
    assert overview.data is not None
    assert detail.data is not None
    assert overview.data.view == "overview"
    assert detail.data.view == "detail"
    assert base64.b64decode(overview.data.data_base64).startswith(b"\x89PNG")
    assert base64.b64decode(detail.data.data_base64).startswith(b"\x89PNG")
    assert len(t2i.templates) == 2
    assert all("UID 1001" in template for template in t2i.templates)
    assert not list((tmp_path / "rendered").glob("*"))


def test_admin_preview_keeps_non_temporary_renderer_path(tmp_path: Path) -> None:
    """非临时资源路径即使被读取也不能被管理预览删除。"""

    path = tmp_path / "provided.png"
    path.write_bytes(b"provided-image")
    rendered = RenderedPlayerImage(
        path=path,
        width=1,
        height=1,
        text_lines=(),
        resources=(),
        sections=(),
    )

    response = AdminPreviewService._image_response(
        rendered,
        user_id="player-1",
        uid="1001",
        view="overview",
    )

    assert response.ok is True
    assert path.exists()
