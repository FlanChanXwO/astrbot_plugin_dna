"""Task 13 玩家查询的 typed fixture、渲染和原图契约。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from shutil import copyfile

import pytest
from PIL import Image, ImageFont

from src.entry.event import EventActor
from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.infrastructure.cache import CacheManager
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import PlayerRenderer, ResourceMap
from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.modules.player import messages
from src.modules.player.cache import PlayerCache
from src.modules.player.contracts import (
    AttributeBag,
    DamageCalculation,
    DamageSkill,
    DamageSnapshot,
    DamageValues,
    Mode,
    PlayerCommandRequest,
    PlayerFailureKind,
    PlayerTransportError,
    RoleAchievement,
    RoleAttribute,
    RoleDetail,
    RoleItem,
    RoleOverview,
    RoleSkill,
    RoleTrace,
    WeaponAttribute,
    WeaponDetail,
    WeaponItem,
)
from src.modules.player.service import PlayerService
from src.modules.privacy import PrivacyService

UID = "1234567890123"
TARGET_UID = "9876543210987"


def _preseed_legacy_assets() -> None:
    """预置 legacy 素材缓存（命中即不下载），使离线渲染可复现。"""

    from src.utils.resource import RESOURCE_PATH

    assets = {
        RESOURCE_PATH.AVATAR_PATH / "avatar_101.png": (180, 60, 60),
        RESOURCE_PATH.AVATAR_PATH / "avatar_102.png": (60, 120, 180),
        RESOURCE_PATH.WEAPON_PATH / "weapon_201.png": (160, 140, 40),
        RESOURCE_PATH.WEAPON_PATH / "weapon_202.png": (80, 160, 80),
        RESOURCE_PATH.ATTR_PATH / "attr_fire.png": (200, 90, 40),
        RESOURCE_PATH.ATTR_PATH / "attr_ice.png": (70, 140, 210),
        RESOURCE_PATH.WEAPON_ATTR_PATH / "attr_close.png": (140, 80, 160),
        RESOURCE_PATH.WEAPON_ATTR_PATH / "attr_ranged.png": (60, 170, 130),
    }
    for path, color in assets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            Image.new("RGBA", (64, 64), color).save(path)


class FixturePlayerTransport:
    """不触碰网络的玩家 API fixture。"""

    def __init__(
        self,
        overview: RoleOverview,
        detail: RoleDetail,
        weapon: WeaponDetail,
        *,
        expected_user_id: str = "user-1",
        expected_uid: str = UID,
        fail_con_weapon: bool = False,
    ) -> None:
        self.overview = overview
        self.detail = detail
        self.weapon = weapon
        self.expected_user_id = expected_user_id
        self.expected_uid = expected_uid
        self.fail_con_weapon = fail_con_weapon
        self.damage_calls = 0
        self.overview_calls = 0
        self.role_detail_calls = 0

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        self.overview_calls += 1
        assert actor.user_id == "user-1"
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_user_id
        return self.overview

    async def get_role_detail(
        self,
        actor: EventActor,
        uid: str,
        char_id: int,
        char_eid: str,
        *,
        credential_user_id: str,
    ) -> RoleDetail:
        self.role_detail_calls += 1
        assert actor.user_id == "user-1"
        assert char_id == 101
        assert char_eid == "char-eid-101"
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_user_id
        return self.detail

    async def get_weapon_detail(
        self,
        actor: EventActor,
        uid: str,
        weapon_id: int,
        weapon_eid: str,
        *,
        credential_user_id: str,
    ) -> WeaponDetail:
        assert actor.user_id == "user-1"
        assert weapon_id in {201, 203}
        assert weapon_eid.startswith("weapon-eid-")
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_user_id
        if self.fail_con_weapon and weapon_id == 203:
            raise PlayerTransportError(
                PlayerFailureKind.SERVER,
                resource="同律武器详情",
                detail="fixture failure",
            )
        return self.weapon

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
        self.damage_calls += 1
        assert actor.user_id == "user-1"
        assert role_detail.char_id == 101
        assert con_weapon is not None or self.fail_con_weapon
        assert close_weapon is not None
        assert ranged_weapon is None
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_user_id
        return DamageCalculation.success(_damage_fixture())


@pytest.mark.asyncio
async def test_role_detail_requests_damage_for_complete_app_card(
    tmp_path: Path,
) -> None:
    """正常角色详情会恢复伤害/显赫相关计算数据并渲染完整详情。"""

    _preseed_legacy_assets()
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(
        _overview_fixture(), _detail_fixture(), _weapon_fixture()
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.role_detail(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
        ),
    )

    assert isinstance(response, ImageResponse)
    assert transport.damage_calls == 1
    artifact = read_rendered_artifact(Path(response.image))
    text = artifact.metadata["dnaby.text"]
    layout = artifact.metadata["dnaby.layout"]
    assert "技能伤害" in text
    assert "伤害" in {section["name"] for section in layout["sections"]}
    await database.dispose()


def _overview_fixture() -> RoleOverview:
    return RoleOverview(
        role_id="role-1",
        role_name="测试玩家",
        level=42,
        params=[
            RoleAchievement(param_key="总活跃天数", param_value="99"),
            RoleAchievement(param_key="自定义成就", param_value="完整保留"),
        ],
        achievement_total=17,
        role_chars=[
            RoleItem(
                char_id=101,
                char_eid="char-eid-101",
                element_icon="element://fire",
                icon="role://101",
                level=80,
                name="角色甲",
                grade_level=6,
                unlocked=True,
            ),
            RoleItem(
                char_id=102,
                char_eid=None,
                element_icon="element://ice",
                icon="role://102",
                level=0,
                name="未解锁角色",
                grade_level=0,
                unlocked=False,
            ),
        ],
        close_weapons=[
            WeaponItem(
                element_icon="weapon-element://close",
                icon="weapon://201",
                level=80,
                name="近战甲",
                unlocked=True,
                weapon_eid="weapon-eid-201",
                weapon_id=201,
                skill_level=5,
            ),
        ],
        ranged_weapons=[
            WeaponItem(
                element_icon="weapon-element://ranged",
                icon="weapon://202",
                level=70,
                name="远程甲",
                unlocked=True,
                weapon_eid="weapon-eid-202",
                weapon_id=202,
                skill_level=4,
            ),
        ],
    )


def _detail_fixture() -> RoleDetail:
    return RoleDetail(
        attribute=RoleAttribute(
            atk=1234,
            max_hp=5678,
            max_es=90,
            defense=321,
            max_sp=88,
            skill_intensity="10%",
            skill_range="20%",
            skill_sustain="30%",
            skill_efficiency="40%",
            strong_value="50%",
            enmity_value="60%",
            weapon_tags=["近战", "测试标签"],
        ),
        skills=[
            RoleSkill(
                skill_id=1000 + index,
                icon=f"skill://{index}",
                level=index + 1,
                skill_name=f"技能{index + 1}",
            )
            for index in range(4)
        ],
        paint="paint://101",
        char_id=101,
        char_name="角色甲",
        element_icon="element://fire",
        traces=[
            RoleTrace(icon="trace://1", description="溯源完整文本 1"),
            RoleTrace(icon="trace://2", description="溯源完整文本 2"),
        ],
        current_volume=3,
        sum_volume=8,
        level=80,
        icon="role://101",
        grade_level=6,
        element_name="火",
        modes=[
            Mode(
                id=3000 + index,
                icon=f"mode://{index}",
                quality=1 + index % 5,
                name=f"魔之楔{index + 1}",
                level=index + 1,
            )
            for index in range(9)
        ],
        con_weapon_eid="weapon-eid-con",
        con_weapon_id=203,
    )


def _weapon_fixture() -> WeaponDetail:
    return WeaponDetail(
        attribute=WeaponAttribute(atk=777, crd=0.1, cri=1.5, speed=0.2, trigger=0.3),
        current_volume=2,
        element_icon="weapon-element://close",
        element_name="近战",
        icon="weapon://201",
        weapon_id=201,
        level=80,
        modes=[
            Mode(id=4001, icon="weapon-mode://1", quality=3, name="武器楔", level=2)
        ],
        name="近战甲",
        skill_level=5,
        sum_volume=8,
    )


def _damage_fixture() -> DamageSnapshot:
    return DamageSnapshot(
        skills=[
            DamageSkill.model_validate(
                {
                    "id": 1,
                    "name": "技能伤害",
                    "normalSkillAttributes": [
                        {"key": "倍率", "value": "100%", "environmentValue": "120%"},
                    ],
                    "damageSkillAttributes": [
                        {"key": "总伤害", "value": 12345, "environmentValue": 13000},
                    ],
                },
            ),
            DamageSkill.model_validate(
                {
                    "id": 2,
                    "name": "派生技能",
                    "parentId": 1,
                    "normalSkillAttributes": [],
                    "damageSkillAttributes": [
                        {"key": "派生伤害", "value": 456},
                    ],
                },
            ),
        ],
        damage=DamageValues(
            close_weapon_damage="1000",
            close_weapon_damage_with_environment="1100",
            con_weapon_damage="2000",
            ranged_weapon_damage="3000",
        ),
        final_attribute=AttributeBag.model_validate(
            {"atk": 2345, "hp": 6789, "extra_metric": 1}
        ),
        base_attribute=AttributeBag(atk=1234, hp=5678),
    )


async def _database_with_binding(
    tmp_path: Path,
    *,
    user_id: str = "user-1",
    uid: str = UID,
) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "player.sqlite3")
    await database.create_schema_for_tests()
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id=user_id,
            uid=uid,
            group_id="group-1",
            is_active=True,
        )
    return database


@pytest.mark.asyncio
async def test_role_overview_returns_runtime_image_and_preserves_all_items(
    tmp_path: Path,
) -> None:
    """概览图是 ImageResponse，合法角色/武器和元数据不能被截断。"""

    _preseed_legacy_assets()
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(
        _overview_fixture(), _detail_fixture(), _weapon_fixture()
    )
    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        renderer,
        show_unowned_roles=True,
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    image_path = Path(response.image)
    assert image_path.parent == tmp_path / "rendered"
    artifact = read_rendered_artifact(image_path)
    assert artifact.width == 1200
    assert artifact.height > 1500  # legacy 布局：头部 800 + 3 分区 × (320+70)
    text = artifact.metadata["dnaby.text"]
    layout = artifact.metadata["dnaby.layout"]
    resources = artifact.metadata["dnaby.resources"]
    assert "测试玩家" in text
    assert "UID 1234567890123" in text
    assert "总活跃天数: 99" in text
    assert "自定义成就: 完整保留" in text
    assert [section["name"] for section in layout["sections"]] == [
        "角色信息",
        "近战武器",
        "远程武器",
    ]
    assert any(
        item["kind"] == "role_avatar" and item["status"] == "legacy_download"
        for item in resources
    )
    assert any(
        item["kind"] == "weapon_icon" and item["status"] == "legacy_download"
        for item in resources
    )
    await database.dispose()


@pytest.mark.asyncio
async def test_role_overview_allows_weapon_without_element_icon(tmp_path: Path) -> None:
    """武器类型图标缺失时仍应渲染总览卡，而不是让整张卡片失败。"""

    _preseed_legacy_assets()
    overview = _overview_fixture()
    overview.close_weapons[0].element_icon = ""
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(overview, _detail_fixture(), _weapon_fixture())
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
        show_unowned_roles=True,
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    artifact = read_rendered_artifact(Path(response.image))
    assert any(
        item["kind"] == "weapon_icon" and item["key"] == "201"
        for item in artifact.metadata["dnaby.resources"]
    )
    await database.dispose()


@pytest.mark.asyncio
async def test_role_overview_allows_role_without_element_icon(tmp_path: Path) -> None:
    """角色类型图标缺失时仍应渲染总览卡，而不是让整张卡片失败。"""

    _preseed_legacy_assets()
    overview = _overview_fixture()
    overview.role_chars[0].element_icon = ""
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(overview, _detail_fixture(), _weapon_fixture())
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
        show_unowned_roles=True,
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    artifact = read_rendered_artifact(Path(response.image))
    assert any(
        item["kind"] == "role_avatar" and item["key"] == "101"
        for item in artifact.metadata["dnaby.resources"]
    )
    await database.dispose()


@pytest.mark.asyncio
async def test_refresh_info_card_only_fetches_overview(tmp_path: Path) -> None:
    """基本信息卡片刷新不能误触发角色详情链路。"""

    _preseed_legacy_assets()
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(
        _overview_fixture(), _detail_fixture(), _weapon_fixture()
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.refresh_info_card(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        )
    )

    assert isinstance(response, ChainResponse)
    assert isinstance(response.components[0], PlainTextResponse)
    assert response.components[0].text == messages.PLAYER_INFO_CARD_REFRESHED
    assert isinstance(response.components[1], ImageResponse)
    assert transport.overview_calls == 1
    assert transport.role_detail_calls == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_clear_info_card_cache_preserves_overview_data_and_detail_cards(
    tmp_path: Path,
) -> None:
    """清理基本信息卡片只删除 overview card，不误伤数据或角色详情卡片。"""

    database = await _database_with_binding(tmp_path)
    manager = CacheManager(tmp_path / "cache")
    cache = PlayerCache(manager, tmp_path / "rendered")
    identity = cache.identity_tag("user-1", UID)
    await manager.put(
        "player_data",
        "overview-data",
        b"{}",
        tags=("player_data", "overview", identity),
    )
    await manager.put(
        "player_card",
        "overview-card",
        b"overview-card",
        tags=("player_card", "overview", identity),
    )
    await manager.put(
        "player_card",
        "detail-card",
        b"detail-card",
        tags=("player_card", "detail", identity),
    )
    service = PlayerService(
        database,
        FixturePlayerTransport(
            _overview_fixture(), _detail_fixture(), _weapon_fixture()
        ),
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
        cache=cache,
    )

    response = await service.clear_info_card_cache(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        )
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.PLAYER_INFO_CARD_CACHE_CLEARED
    assert (await manager.get("player_data", "overview-data")).status == "fresh"
    assert (await manager.get("player_card", "overview-card")).status == "miss"
    assert (await manager.get("player_card", "detail-card")).status == "fresh"
    await database.dispose()


@pytest.mark.asyncio
async def test_player_query_uses_target_account_credentials(tmp_path: Path) -> None:
    """@ 他人查询时 transport 必须使用目标用户的凭据所有者。"""

    _preseed_legacy_assets()
    database = await _database_with_binding(
        tmp_path, user_id="target-1", uid=TARGET_UID
    )
    transport = FixturePlayerTransport(
        _overview_fixture(),
        _detail_fixture(),
        _weapon_fixture(),
        expected_user_id="target-1",
        expected_uid=TARGET_UID,
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id="target-1",
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    await database.dispose()


@pytest.mark.asyncio
async def test_role_detail_renders_all_basic_sections_and_original_path(
    tmp_path: Path,
) -> None:
    """详情图保留基础角色资料、技能、魔之楔和武器字段。"""

    original = tmp_path / "original-panel.png"
    Image.new("RGBA", (37, 53), "purple").save(original)
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(
        _overview_fixture(), _detail_fixture(), _weapon_fixture()
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(original_panels={"101": original}),
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        renderer,
    )

    response = await service.role_detail(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    assert response.original_image_path == original
    artifact = read_rendered_artifact(Path(response.image))
    assert artifact.width == 1000
    text = artifact.metadata["dnaby.text"]
    layout = artifact.metadata["dnaby.layout"]
    resources = artifact.metadata["dnaby.resources"]
    for expected in ("角色甲", "技能1", "技能4", "魔之楔1", "魔之楔9", "近战甲"):
        assert expected in text
    assert [section["name"] for section in layout["sections"]] == [
        "角色头部",
        "角色属性",
        "技能",
        "溯源",
        "武器",
        "魔之楔",
    ]
    assert any(
        item["kind"] == "original_panel" and item["status"] == "provided"
        for item in resources
    )
    original_response = await service.original_image(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1"),
            target_user_id=None,
            reply_id="message-detail",
        ),
    )
    assert isinstance(original_response, PlainTextResponse)
    assert original_response.text == messages.PLAYER_ORIGINAL_UNSUPPORTED
    await database.dispose()


@pytest.mark.asyncio
async def test_concurrent_role_details_keep_their_related_original_paths(
    tmp_path: Path,
) -> None:
    """同一 service 的并发详情响应必须各自关联自己的原始面板。"""

    class ConcurrentTransport(FixturePlayerTransport):
        async def get_role_detail(
            self,
            actor: EventActor,
            uid: str,
            char_id: int,
            char_eid: str,
            *,
            credential_user_id: str,
        ) -> RoleDetail:
            await asyncio.sleep(0)
            assert actor.user_id == "user-1"
            assert uid == UID
            assert credential_user_id == "user-1"
            assert char_eid == f"char-eid-{char_id}"
            detail = _detail_fixture()
            return detail.model_copy(
                update={
                    "char_id": char_id,
                    "char_name": "角色甲" if char_id == 101 else "角色乙",
                    "paint": f"paint://{char_id}",
                    "icon": f"role://{char_id}",
                },
            )

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
            await asyncio.sleep(0)
            assert actor.user_id == "user-1"
            assert uid == UID
            assert role_detail.char_id in {101, 102}
            assert con_weapon is not None
            assert close_weapon is not None
            assert ranged_weapon is None
            assert credential_user_id == "user-1"
            return DamageCalculation.success(_damage_fixture())

    original_one = tmp_path / "original-101.png"
    original_two = tmp_path / "original-102.png"
    Image.new("RGBA", (37, 53), "purple").save(original_one)
    Image.new("RGBA", (37, 53), "teal").save(original_two)
    overview = _overview_fixture().model_copy(
        update={
            "role_chars": [
                _overview_fixture().role_chars[0],
                RoleItem(
                    char_id=102,
                    char_eid="char-eid-102",
                    element_icon="element://ice",
                    icon="role://102",
                    level=70,
                    name="角色乙",
                    grade_level=5,
                    unlocked=True,
                ),
            ],
        },
    )
    database = await _database_with_binding(tmp_path)
    service = PlayerService(
        database,
        ConcurrentTransport(overview, _detail_fixture(), _weapon_fixture()),
        PrivacyService(database),
        PlayerRenderer(
            tmp_path / "rendered",
            ResourceMap(original_panels={"101": original_one, "102": original_two}),
        ),
    )

    first, second = await asyncio.gather(
        service.role_detail(
            PlayerCommandRequest(
                actor=EventActor("user-1", "bot-1", "group-1"),
                target_user_id=None,
                parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
            ),
        ),
        service.role_detail(
            PlayerCommandRequest(
                actor=EventActor("user-1", "bot-1", "group-1"),
                target_user_id=None,
                parameters={"char_name": "角色乙", "weapon_name_1": "近战甲"},
            ),
        ),
    )

    assert isinstance(first, ImageResponse)
    assert isinstance(second, ImageResponse)
    assert first.original_image_path == original_one
    assert second.original_image_path == original_two
    assert not hasattr(service, "last_original_image")
    await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_message",
    (
        "token=secret-token-001",
        "Cookie: session=secret-cookie-002",
        "dev_code=secret-device-003",
        "Authorization: Bearer secret-auth-004",
        "Bearer secret-bearer-005",
        "https://api.example.test/damage?token=secret-url-006",
    ),
)
async def test_damage_failure_hides_optional_detail_section(
    tmp_path: Path,
    upstream_message: str,
) -> None:
    """伤害计算失败或不受支持时，整个可选伤害区块都应隐藏。"""

    class SensitiveDamageTransport(FixturePlayerTransport):
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
            assert actor.user_id == "user-1"
            assert uid == UID
            assert role_detail.char_id == 101
            assert con_weapon is not None
            assert close_weapon is not None
            assert ranged_weapon is None
            assert credential_user_id == "user-1"
            return DamageCalculation.failure(upstream_message)

    database = await _database_with_binding(tmp_path)
    transport = SensitiveDamageTransport(
        _overview_fixture(),
        _detail_fixture(),
        _weapon_fixture(),
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.role_detail(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.original_image_path is None
    assert upstream_message not in repr(response)
    artifact = read_rendered_artifact(Path(response.image))
    text = artifact.metadata["dnaby.text"]
    layout = artifact.metadata["dnaby.layout"]
    resources = artifact.metadata["dnaby.resources"]
    assert messages.PLAYER_DAMAGE_FAILED not in text
    assert upstream_message not in text
    assert upstream_message not in layout
    assert upstream_message not in resources
    assert "伤害" not in {section["name"] for section in layout["sections"]}
    await database.dispose()


@pytest.mark.asyncio
async def test_player_renderer_marks_runtime_root_assets_and_missing_values(
    tmp_path: Path,
) -> None:
    """玩家图片的资源 metadata 必须区分私有根提供的素材与 placeholder。"""

    resource_root = tmp_path / "resources"
    font_source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    font = resource_root / "fonts" / "dna_fonts.ttf"
    avatar = resource_root / "images" / "role_avatar" / "101.png"
    paint = resource_root / "images" / "role_paint" / "101.png"
    panel = resource_root / "panel" / "101.png"
    for path, color in ((avatar, "red"), (paint, "blue"), (panel, "purple")):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (17, 19), color).save(path)
    font.parent.mkdir(parents=True, exist_ok=True)
    copyfile(font_source, font)
    renderer = PlayerRenderer(
        tmp_path / "rendered", ResourceMap.from_root(resource_root)
    )

    overview = await renderer.render_overview(
        _overview_fixture(),
        uid=UID,
        uid_hidden=False,
    )
    detail = await renderer.render_detail(
        _detail_fixture(),
        [("近战", _weapon_fixture())],
        DamageCalculation.success(_damage_fixture()),
        uid=UID,
        uid_hidden=False,
    )

    assert any(
        item["kind"] == "font" and item["status"] == "provided"
        for item in overview.resources
    )
    assert any(
        item["kind"] == "role_avatar"
        and item["key"] == "101"
        and item["status"] == "provided"
        for item in overview.resources
    )
    assert any(
        item["kind"] == "role_avatar"
        and item["key"] == "102"
        and item["status"] == "placeholder"
        for item in overview.resources
    )
    assert any(
        item["kind"] == "role_paint" and item["status"] == "provided"
        for item in detail.resources
    )
    assert any(
        item["kind"] == "original_panel" and item["status"] == "provided"
        for item in detail.resources
    )


@pytest.mark.asyncio
async def test_role_detail_exposes_con_weapon_failure(tmp_path: Path) -> None:
    """同律武器读取失败不得静默降级为缺少武器。"""

    database = await _database_with_binding(tmp_path)
    service = PlayerService(
        database,
        FixturePlayerTransport(
            _overview_fixture(),
            _detail_fixture(),
            _weapon_fixture(),
            fail_con_weapon=True,
        ),
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.role_detail(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert "服务" in response.text
    await database.dispose()


@pytest.mark.asyncio
async def test_original_image_reports_unsupported_without_public_delivery_id(
    tmp_path: Path,
) -> None:
    """没有发送后消息 ID 时，原图命令必须显式报告未支持。"""

    database = await _database_with_binding(tmp_path)
    service = PlayerService(
        database,
        FixturePlayerTransport(
            _overview_fixture(), _detail_fixture(), _weapon_fixture()
        ),
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.original_image(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1"),
            target_user_id=None,
            reply_id="message-101",
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.PLAYER_ORIGINAL_UNSUPPORTED
    await database.dispose()


@pytest.mark.asyncio
async def test_player_query_errors_are_visible_and_typed(tmp_path: Path) -> None:
    """无绑定和无引用属于可诊断文本，不得伪造空图片或静默成功。"""

    database = AsyncDatabase(tmp_path / "player.sqlite3")
    await database.create_schema_for_tests()
    service = PlayerService(
        database,
        FixturePlayerTransport(
            _overview_fixture(), _detail_fixture(), _weapon_fixture()
        ),
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
    )

    response = await service.role_overview(
        PlayerCommandRequest(actor=EventActor("user-1", "bot-1"), target_user_id=None),
    )
    original_response = await service.original_image(
        PlayerCommandRequest(actor=EventActor("user-1", "bot-1"), target_user_id=None),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == "当前未绑定账号，请先登录"
    assert isinstance(original_response, PlainTextResponse)
    assert "引用" in original_response.text
    await database.dispose()


def test_player_renderer_uses_bundled_chinese_font_without_private_resources(
    tmp_path: Path,
) -> None:
    """私有字体缺失时仍须使用随包中文字体，不能退回拉丁默认字体产生方块。"""

    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())

    assert isinstance(renderer._font(19), ImageFont.FreeTypeFont)


def test_resource_map_random_panel_background_returns_none_when_unavailable(
    tmp_path: Path,
) -> None:
    """无运行期 panel 图集时随机 hero 背景必须返回 None，不伪造素材或指向不存在文件。"""

    assert ResourceMap().random_panel_background() is None
    empty_root = tmp_path / "empty"
    assert ResourceMap.from_root(empty_root).random_panel_background() is None
    panel_root = empty_root / "panel"
    panel_root.mkdir(parents=True)
    (panel_root / ".gitkeep").write_text("", encoding="utf-8")
    assert ResourceMap.from_root(empty_root).random_panel_background() is None


def test_resource_map_random_panel_background_selects_image_from_panel(
    tmp_path: Path,
) -> None:
    """panel 图集存在时随机背景从其中取一张合法图片，忽略非图片文件。"""

    panel_root = tmp_path / "resources" / "panel"
    panel_root.mkdir(parents=True)
    Image.new("RGBA", (48, 24), "red").save(panel_root / "panel_1.png")
    Image.new("RGB", (48, 24), "blue").save(panel_root / "panel_2.jpg")
    (panel_root / ".gitkeep").write_text("", encoding="utf-8")
    mapped = ResourceMap.from_root(tmp_path / "resources")

    picked = mapped.random_panel_background()

    assert picked is not None
    assert picked.parent == panel_root
    assert picked.name in {"panel_1.png", "panel_2.jpg"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "with_panel",
    [True, False],
    ids=["provided", "fallback"],
)
async def test_role_overview_records_panel_background_and_passes_hero_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_panel: bool,
) -> None:
    """基本信息卡 hero 背景取运行期 panel/ 随机图并记录 metadata；无图集时标 fallback。

    mock 渲染函数捕获透传的 hero_background_path，避免把每次随机选择与真实 T2I
    渲染耦合；render_overview 的 metadata 构造与 artifact 写入仍真实执行。
    """

    import src.infrastructure.rendering.player as player_module

    captured: dict[str, object] = {}

    async def fake_overview(*args: object, **kwargs: object) -> bytes:
        captured.update(kwargs)
        buffer = BytesIO()
        Image.new("RGB", (12, 16), "#335577").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module, "draw_role_info_card_core", fake_overview)
    resource_root = tmp_path / "resources"
    if with_panel:
        panel_dir = resource_root / "panel"
        panel_dir.mkdir(parents=True)
        Image.new("RGB", (48, 24), "#4b1f7a").save(panel_dir / "panel_1.png")
    renderer = PlayerRenderer(
        tmp_path / "rendered", ResourceMap.from_root(resource_root)
    )

    overview = await renderer.render_overview(
        _overview_fixture(),
        uid=UID,
        uid_hidden=False,
    )

    hero_path = captured.get("hero_background_path")
    if with_panel:
        assert hero_path is not None
        assert hero_path.name == "panel_1.png"
        expected_status = "provided"
        expected_source = "panel/panel_1.png"
    else:
        assert hero_path is None
        expected_status = "fallback"
        expected_source = "panel/"
    assert any(
        item["kind"] == "panel_background"
        and item["status"] == expected_status
        and item["source"] == expected_source
        for item in overview.resources
    )


def _protagonist_overview(*, male: bool) -> RoleOverview:
    """构造只拥有单侧性别的账号概览；玩家不可能同时拥有男女主角。"""

    prefix = "男主" if male else "女主"
    return RoleOverview(
        role_id="role-1",
        role_name="测试玩家",
        level=80,
        role_chars=[
            RoleItem(
                char_id=160101 if male else 1601,
                char_eid=f"char-eid-{prefix}光",
                element_icon="element://light",
                icon="role://light",
                level=80,
                name=f"{prefix}-光",
                grade_level=6,
                unlocked=True,
            ),
            RoleItem(
                char_id=120101 if male else 1201,
                char_eid=f"char-eid-{prefix}暗",
                element_icon="element://dark",
                icon="role://dark",
                level=80,
                name=f"{prefix}-暗",
                grade_level=6,
                unlocked=True,
            ),
        ],
    )


def test_protagonist_aliases_follow_owned_gender() -> None:
    """性别未知的主角称呼按玩家实际拥有的席位解析，而不是写死女主。"""

    female = _protagonist_overview(male=False)
    male = _protagonist_overview(male=True)

    assert PlayerService._find_role(female, "主角").name == "女主-光"
    assert PlayerService._find_role(male, "主角").name == "男主-光"
    assert PlayerService._find_role(female, "光主").name == "女主-光"
    assert PlayerService._find_role(male, "光主").name == "男主-光"
    assert PlayerService._find_role(female, "暗主").name == "女主-暗"
    assert PlayerService._find_role(male, "暗主").name == "男主-暗"


def test_protagonist_aliases_never_conflate_genders() -> None:
    """同名主角素材不同，男女必须解析到各自的规范名与 char_id。"""

    female = _protagonist_overview(male=False)
    male = _protagonist_overview(male=True)

    for alias in ("主角", "光主", "暗主"):
        female_role = PlayerService._find_role(female, alias)
        male_role = PlayerService._find_role(male, alias)
        assert female_role is not None and male_role is not None
        assert female_role.name != male_role.name
        assert female_role.char_id != male_role.char_id
