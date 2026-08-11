"""Task 13 玩家查询的 typed fixture、渲染和原图契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ImageResponse, PlainTextResponse
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering import (
    OriginalImageCache,
    PlayerRenderer,
    ResourceMap,
)
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

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
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
        assert actor.user_id == "user-1"
        assert role_detail.char_id == 101
        assert con_weapon is not None or self.fail_con_weapon
        assert close_weapon is not None
        assert ranged_weapon is None
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_user_id
        return DamageCalculation.success(_damage_fixture())


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
        modes=[Mode(id=4001, icon="weapon-mode://1", quality=3, name="武器楔", level=2)],
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
        final_attribute=AttributeBag.model_validate({"atk": 2345, "hp": 6789, "extra_metric": 1}),
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
            bot_id="bot-1",
            uid=uid,
            group_id="group-1",
            is_active=True,
        )
    return database


@pytest.mark.asyncio
async def test_role_overview_returns_runtime_image_and_preserves_all_items(tmp_path: Path) -> None:
    """概览图是 ImageResponse，合法角色/武器和元数据不能被截断。"""

    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(_overview_fixture(), _detail_fixture(), _weapon_fixture())
    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        renderer,
        OriginalImageCache(),
        show_unowned_roles=True,
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ImageResponse)
    image_path = Path(response.image)
    assert image_path.parent == tmp_path / "rendered"
    with Image.open(image_path) as image:
        assert image.width == 1200
        assert image.height > 800
        text = image.info["dnaby.text"]
        layout = json.loads(image.info["dnaby.layout"])
        resources = json.loads(image.info["dnaby.resources"])
    assert "角色甲" in text
    assert "未解锁角色" in text
    assert "近战甲" in text
    assert "远程甲" in text
    assert "自定义成就: 完整保留" in text
    assert [section["name"] for section in layout["sections"]] == [
        "角色信息",
        "近战武器",
        "远程武器",
    ]
    assert any(item["status"] == "placeholder" for item in resources)
    await database.dispose()


@pytest.mark.asyncio
async def test_player_query_uses_target_account_credentials(tmp_path: Path) -> None:
    """@ 他人查询时 transport 必须使用目标用户的凭据所有者。"""

    database = await _database_with_binding(tmp_path, user_id="target-1", uid=TARGET_UID)
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
        OriginalImageCache(),
    )

    response = await service.role_overview(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id="target-1",
        ),
    )

    assert isinstance(response, ImageResponse)
    await database.dispose()


@pytest.mark.asyncio
async def test_role_detail_renders_all_skills_modes_damage_and_original_path(tmp_path: Path) -> None:
    """详情图按动态高度渲染所有技能、魔之楔和伤害字段。"""

    original = tmp_path / "original-panel.png"
    Image.new("RGBA", (37, 53), "purple").save(original)
    database = await _database_with_binding(tmp_path)
    transport = FixturePlayerTransport(_overview_fixture(), _detail_fixture(), _weapon_fixture())
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(original_panels={"101": original}),
    )
    service = PlayerService(
        database,
        transport,
        PrivacyService(database),
        renderer,
        OriginalImageCache(),
    )

    response = await service.role_detail(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "角色甲", "weapon_name_1": "近战甲"},
        ),
    )

    assert isinstance(response, ImageResponse)
    with Image.open(Path(response.image)) as image:
        assert image.width == 1000
        assert image.height > 1500
        text = image.info["dnaby.text"]
        layout = json.loads(image.info["dnaby.layout"])
        resources = json.loads(image.info["dnaby.resources"])
    for expected in ("角色甲", "技能1", "技能4", "魔之楔1", "魔之楔9", "近战甲", "技能伤害", "派生技能", "总伤害"):
        assert expected in text
    assert [section["name"] for section in layout["sections"]] == [
        "角色头部",
        "角色属性",
        "技能",
        "溯源",
        "武器",
        "魔之楔",
        "伤害",
    ]
    assert any(item["kind"] == "original_panel" and item["status"] == "provided" for item in resources)
    assert service.last_original_image == original
    service.remember_original_image(("message-detail",))
    original_response = await service.original_image(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1"),
            target_user_id=None,
            reply_id="message-detail",
        ),
    )
    assert isinstance(original_response, ImageResponse)
    assert original_response.image == str(original)
    await database.dispose()


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
        OriginalImageCache(),
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
async def test_original_image_uses_quoted_message_cache(tmp_path: Path) -> None:
    """原图命令只返回显式缓存的原图，不把详情合成图冒充原图。"""

    original = tmp_path / "original.png"
    Image.new("RGB", (11, 13), "blue").save(original)
    database = await _database_with_binding(tmp_path)
    cache = OriginalImageCache()
    cache.remember(("message-101",), original)
    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    service = PlayerService(
        database,
        FixturePlayerTransport(_overview_fixture(), _detail_fixture(), _weapon_fixture()),
        PrivacyService(database),
        renderer,
        cache,
    )

    response = await service.original_image(
        PlayerCommandRequest(
            actor=EventActor("user-1", "bot-1"),
            target_user_id=None,
            reply_id="message-101",
        ),
    )

    assert isinstance(response, ImageResponse)
    assert response.image == str(original)
    await database.dispose()


@pytest.mark.asyncio
async def test_player_query_errors_are_visible_and_typed(tmp_path: Path) -> None:
    """无绑定和无引用属于可诊断文本，不得伪造空图片或静默成功。"""

    database = AsyncDatabase(tmp_path / "player.sqlite3")
    await database.create_schema_for_tests()
    service = PlayerService(
        database,
        FixturePlayerTransport(_overview_fixture(), _detail_fixture(), _weapon_fixture()),
        PrivacyService(database),
        PlayerRenderer(tmp_path / "rendered", ResourceMap()),
        OriginalImageCache(),
    )

    response = await service.role_overview(
        PlayerCommandRequest(actor=EventActor("user-1", "bot-1"), target_user_id=None),
    )
    original_response = await service.original_image(
        PlayerCommandRequest(actor=EventActor("user-1", "bot-1"), target_user_id=None),
    )

    assert isinstance(response, PlainTextResponse)
    assert "UID无效" in response.text
    assert isinstance(original_response, PlainTextResponse)
    assert "引用" in original_response.text
    await database.dispose()
