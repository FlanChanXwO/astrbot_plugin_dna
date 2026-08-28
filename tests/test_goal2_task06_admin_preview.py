"""Goal 2 / Task 06：管理员玩家预览 service 契约。"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio

from src.entry.event import EventActor
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import RenderedPlayerImage
from src.modules.admin import (
    AdminPreviewImage,
    AdminPreviewRequest,
    AdminPreviewService,
)
from src.modules.player.contracts import (
    AttributeBag,
    DamageCalculation,
    DamageSnapshot,
    DamageValues,
    PlayerFailureKind,
    PlayerTransportError,
    RoleAttribute,
    RoleDetail,
    RoleItem,
    RoleOverview,
    WeaponAttribute,
    WeaponDetail,
    WeaponItem,
)
from src.modules.privacy import PrivacyService


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[AsyncDatabase]:
    """为管理员预览测试提供隔离数据库。"""

    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


def _overview() -> RoleOverview:
    return RoleOverview(
        role_id="role-1",
        role_name="目标玩家",
        role_chars=[
            RoleItem(
                char_id=101,
                char_eid="char-eid-101",
                name="角色甲",
                unlocked=True,
            ),
        ],
        close_weapons=[
            WeaponItem(
                weapon_id=201,
                weapon_eid="weapon-eid-201",
                name="近战甲",
                unlocked=True,
            ),
        ],
    )


def _detail() -> RoleDetail:
    return RoleDetail(
        attribute=RoleAttribute(),
        char_id=101,
        char_name="角色甲",
    )


def _weapon() -> WeaponDetail:
    return WeaponDetail(
        attribute=WeaponAttribute(),
        weapon_id=201,
        name="近战甲",
    )


def _damage() -> DamageCalculation:
    return DamageCalculation.success(
        DamageSnapshot(
            damage=DamageValues(),
            final_attribute=AttributeBag(),
            base_attribute=AttributeBag(),
        ),
    )


class RecordingTransport:
    """记录 admin preview 传给既有 player transport 的全局身份参数。"""

    def __init__(self) -> None:
        self.overview_calls: list[tuple[str, str, str]] = []
        self.detail_calls: list[tuple[str, str, int, str, str]] = []
        self.weapon_calls: list[tuple[str, str, int, str, str]] = []
        self.damage_calls: list[tuple[str, str, str]] = []

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        self.overview_calls.append((actor.user_id, uid, credential_user_id))
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
        self.detail_calls.append(
            (actor.user_id, uid, char_id, char_eid, credential_user_id)
        )
        return _detail()

    async def get_weapon_detail(
        self,
        actor: EventActor,
        uid: str,
        weapon_id: int,
        weapon_eid: str,
        *,
        credential_user_id: str,
    ) -> WeaponDetail:
        self.weapon_calls.append(
            (actor.user_id, uid, weapon_id, weapon_eid, credential_user_id)
        )
        return _weapon()

    async def calculate_damage(
        self,
        actor: EventActor,
        uid: str,
        role_detail: RoleDetail,
        con_weapon: WeaponDetail | None,
        close_weapon: WeaponDetail | None,
        ranged_weapon: WeaponDetail | None,
        *,
        credential_user_id: str,
    ) -> DamageCalculation:
        del con_weapon, close_weapon, ranged_weapon
        self.damage_calls.append((actor.user_id, uid, credential_user_id))
        assert role_detail.char_id == 101
        return _damage()


class RecordingRenderer:
    """返回无路径 DTO 之前的最小 renderer 结果，并记录固定渲染参数。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.overview_kwargs: dict[str, Any] | None = None
        self.detail_kwargs: dict[str, Any] | None = None

    def _result(self, name: str, payload: bytes) -> RenderedPlayerImage:
        path = self.output_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return RenderedPlayerImage(
            path=path,
            width=100,
            height=80,
            text_lines=(name,),
            resources=(),
            sections=(),
            temporary=True,
        )

    async def render_overview(
        self, overview: RoleOverview, **kwargs: Any
    ) -> RenderedPlayerImage:
        del overview
        self.overview_kwargs = kwargs
        return self._result("overview.png", b"overview-image")

    async def render_detail(
        self, detail: RoleDetail, weapons: Any, damage: Any, **kwargs: Any
    ) -> RenderedPlayerImage:
        del detail, weapons, damage
        self.detail_kwargs = kwargs
        return self._result("detail.png", b"detail-image")


async def _seed_binding(database: AsyncDatabase) -> None:
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="player-1",
            uid="1001",
            group_id="group-1",
            is_active=True,
        )


def _request(*, detail: bool = False) -> AdminPreviewRequest:
    return AdminPreviewRequest(
        actor=EventActor("dashboard-admin", "bot-1", "group-1"),
        user_id="player-1",
        uid="1001",
        char_name="角色甲" if detail else None,
        weapon_names=("近战甲",) if detail else (),
    )


@pytest.mark.asyncio
async def test_admin_overview_bypasses_privacy_and_returns_path_free_image(
    database: AsyncDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_binding(database)
    transport = RecordingTransport()
    renderer = RecordingRenderer(tmp_path / "rendered")

    async def fail_privacy(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("admin preview 不得调用 PrivacyService")

    monkeypatch.setattr(PrivacyService, "resolve_query", fail_privacy)
    service = AdminPreviewService(database, cast(Any, transport), cast(Any, renderer))

    response = await service.preview_overview(_request())

    assert response.ok is True
    assert response.cache_control == "no-store"
    assert response.data is not None
    assert isinstance(response.data, AdminPreviewImage)
    assert response.data.view == "overview"
    assert response.data.uid == "1001"
    assert response.data.user_id == "player-1"
    assert response.data.width == 100
    assert response.data.height == 80
    assert response.data.data_base64
    assert "rendered" not in repr(response.data)
    assert "path" not in response.data.to_dict()
    assert transport.overview_calls == [("dashboard-admin", "1001", "player-1")]
    assert renderer.overview_kwargs is not None
    assert renderer.overview_kwargs["uid_hidden"] is False
    assert renderer.overview_kwargs["target_user_id"] == "player-1"
    assert renderer.overview_kwargs["show_unowned"] is True


@pytest.mark.asyncio
async def test_admin_detail_reuses_role_and_weapon_selection_with_complete_uid(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_binding(database)
    transport = RecordingTransport()
    renderer = RecordingRenderer(tmp_path / "rendered")
    service = AdminPreviewService(database, cast(Any, transport), cast(Any, renderer))

    response = await service.preview_detail(_request(detail=True))

    assert response.ok is True
    assert response.data is not None and response.data.view == "detail"
    assert transport.overview_calls == [("dashboard-admin", "1001", "player-1")]
    assert transport.detail_calls == [
        ("dashboard-admin", "1001", 101, "char-eid-101", "player-1"),
    ]
    assert transport.weapon_calls == [
        ("dashboard-admin", "1001", 201, "weapon-eid-201", "player-1"),
    ]
    assert transport.damage_calls == [("dashboard-admin", "1001", "player-1")]
    assert renderer.detail_kwargs is not None
    assert renderer.detail_kwargs["uid_hidden"] is False
    assert renderer.detail_kwargs["uid"] == "1001"
    assert renderer.detail_kwargs["target_user_id"] == "player-1"


@pytest.mark.asyncio
async def test_admin_preview_maps_upstream_and_render_errors_without_raw_details(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_binding(database)

    class FailingTransport(RecordingTransport):
        async def get_overview(
            self,
            actor: EventActor,
            uid: str,
            *,
            credential_user_id: str,
        ) -> RoleOverview:
            del actor, uid, credential_user_id
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK,
                resource="角色列表信息",
                detail="Authorization: Bearer secret-preview-token",
            )

    transport_response = await AdminPreviewService(
        database,
        cast(Any, FailingTransport()),
        cast(Any, RecordingRenderer(tmp_path / "transport-rendered")),
    ).preview_overview(_request())
    assert transport_response.ok is False
    assert transport_response.error is not None
    assert transport_response.error.code == "upstream"
    assert "secret-preview-token" not in repr(transport_response)

    class FailingRenderer(RecordingRenderer):
        async def render_overview(
            self, overview: RoleOverview, **kwargs: Any
        ) -> RenderedPlayerImage:
            del overview, kwargs
            from src.infrastructure.rendering import TemplateRenderError

            raise TemplateRenderError(
                "private path /tmp/secret-preview", cause=RuntimeError("secret")
            )

    render_response = await AdminPreviewService(
        database,
        cast(Any, RecordingTransport()),
        cast(Any, FailingRenderer(tmp_path / "rendered")),
    ).preview_overview(_request())
    assert render_response.ok is False
    assert render_response.error is not None
    assert render_response.error.code == "internal"
    assert "secret-preview" not in repr(render_response)
    assert "/tmp" not in repr(render_response)


@pytest.mark.asyncio
async def test_admin_preview_maps_damage_failure_to_upstream_without_rendering(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_binding(database)

    class FailingDamageTransport(RecordingTransport):
        async def calculate_damage(
            self,
            actor: EventActor,
            uid: str,
            role_detail: RoleDetail,
            con_weapon: WeaponDetail | None,
            close_weapon: WeaponDetail | None,
            ranged_weapon: WeaponDetail | None,
            *,
            credential_user_id: str,
        ) -> DamageCalculation:
            del actor, uid, role_detail, con_weapon, close_weapon, ranged_weapon
            del credential_user_id
            raise PlayerTransportError(
                PlayerFailureKind.NETWORK,
                resource="伤害计算",
                detail="secret-damage-token",
            )

    renderer = RecordingRenderer(tmp_path / "rendered")
    response = await AdminPreviewService(
        database,
        cast(Any, FailingDamageTransport()),
        cast(Any, renderer),
    ).preview_detail(_request(detail=True))

    assert response.ok is False
    assert response.error is not None and response.error.code == "upstream"
    assert "secret-damage-token" not in repr(response)
    assert renderer.detail_kwargs is None


@pytest.mark.asyncio
async def test_admin_preview_rejects_empty_rendered_image(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    await _seed_binding(database)

    class EmptyRenderer(RecordingRenderer):
        async def render_overview(
            self,
            overview: RoleOverview,
            **kwargs: Any,
        ) -> RenderedPlayerImage:
            del overview, kwargs
            return self._result("empty.png", b"")

    response = await AdminPreviewService(
        database,
        cast(Any, RecordingTransport()),
        cast(Any, EmptyRenderer(tmp_path / "rendered")),
    ).preview_overview(_request())

    assert response.ok is False
    assert response.error is not None and response.error.code == "internal"


@pytest.mark.asyncio
async def test_admin_preview_rejects_unbound_identity_without_calling_transport(
    database: AsyncDatabase,
    tmp_path: Path,
) -> None:
    transport = RecordingTransport()
    service = AdminPreviewService(
        database,
        cast(Any, transport),
        cast(Any, RecordingRenderer(tmp_path / "rendered")),
    )

    response = await service.preview_overview(
        AdminPreviewRequest(
            actor=EventActor("dashboard-admin", "bot-1"),
            user_id="missing-user",
            uid="9999",
        ),
    )

    assert response.ok is False
    assert response.error is not None and response.error.code == "not_found"
    assert transport.overview_calls == []
