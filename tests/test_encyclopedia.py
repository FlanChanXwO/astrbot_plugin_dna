"""Task 14 资料查询的 typed fixture、图片、消息链和别名契约。"""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from src.infrastructure.rendering.encyclopedia import EncyclopediaRenderer
from src.infrastructure.resources.encyclopedia import (
    AliasCatalog,
    EncyclopediaResourceStore,
    GuideAsset,
)
from src.modules.encyclopedia.contracts import (
    CalendarEvent,
    CalendarSnapshot,
    CodeEntry,
    CodeSnapshot,
    DraftSnapshot,
    EncyclopediaRequest,
    EncyclopediaTransportError,
    PlayerShortNote,
    WeeklyReport,
    WeeklyReportCategory,
    WeeklyReportItem,
)
from src.modules.encyclopedia.service import EncyclopediaService
from src.modules.player.contracts import RoleAchievement, RoleOverview
from src.modules.privacy import PrivacyService

SHANGHAI = ZoneInfo("Asia/Shanghai")
UID = "1234567890123"
TARGET_UID = "9876543210123"


class FixtureEncyclopediaTransport:
    """不触碰网络的资料 API fixture。"""

    def __init__(
        self,
        short_note: PlayerShortNote,
        weekly: WeeklyReport,
        calendar: CalendarSnapshot,
        codes: CodeSnapshot,
        *,
        error: EncyclopediaTransportError | None = None,
        expected_actor_user_id: str = "user-1",
        expected_uid: str = UID,
        expected_credential_user_id: str = "user-1",
    ) -> None:
        self.short_note = short_note
        self.weekly = weekly
        self.calendar = calendar
        self.codes = codes
        self.error = error
        self.expected_actor_user_id = expected_actor_user_id
        self.expected_uid = expected_uid
        self.expected_credential_user_id = expected_credential_user_id
        self.calls: list[tuple[str, str | int | None]] = []

    async def get_short_note(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> PlayerShortNote:
        self.calls.append(("short_note", credential_user_id))
        assert actor.user_id == self.expected_actor_user_id
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_credential_user_id
        if self.error is not None:
            raise self.error
        return self.short_note

    async def get_weekly_report(
        self,
        actor: EventActor,
        uid: str,
        week_type: int,
        *,
        credential_user_id: str,
    ) -> WeeklyReport:
        self.calls.append(("weekly", week_type))
        assert actor.user_id == self.expected_actor_user_id
        assert uid == self.expected_uid
        assert credential_user_id == self.expected_credential_user_id
        if self.error is not None:
            raise self.error
        return self.weekly

    async def get_calendar(self, actor: EventActor) -> CalendarSnapshot:
        self.calls.append(("calendar", None))
        assert actor.user_id == self.expected_actor_user_id
        if self.error is not None:
            raise self.error
        return self.calendar

    async def get_codes(self, actor: EventActor) -> CodeSnapshot:
        self.calls.append(("codes", None))
        assert actor.user_id == self.expected_actor_user_id
        if self.error is not None:
            raise self.error
        return self.codes


def _role_overview() -> RoleOverview:
    return RoleOverview(
        role_id="role-1",
        role_name="资料玩家",
        level=55,
        params=[
            RoleAchievement(param_key="总活跃天数", param_value="88"),
            RoleAchievement(param_key="游戏时长", param_value="123小时"),
            RoleAchievement(param_key="额外统计", param_value="完整保留"),
        ],
        achievement_total=21,
    )


def _short_note() -> PlayerShortNote:
    return PlayerShortNote(
        rouge_like_reward_count=2,
        rouge_like_reward_total=5,
        current_task_progress=3,
        max_daily_task_progress=6,
        hard_boss_reward_count=4,
        hard_boss_reward_total=8,
        dungeon_reward=1,
        dungeon_reward_total=3,
        drafts=(
            DraftSnapshot(
                product_name="测试矿石",
                start_at=datetime(2026, 8, 11, 8, 0, tzinfo=SHANGHAI),
                end_at=datetime(2026, 8, 11, 12, 0, tzinfo=SHANGHAI),
                completed=False,
                draft_doing_num=3,
                draft_complete_num=2,
            ),
            DraftSnapshot(
                product_name="完成材料",
                start_at=datetime(2026, 8, 10, 8, 0, tzinfo=SHANGHAI),
                end_at=datetime(2026, 8, 10, 12, 0, tzinfo=SHANGHAI),
                completed=True,
                draft_doing_num=0,
                draft_complete_num=4,
            ),
        ),
        draft_doing_num=3,
        draft_max_num=5,
        role_overview=_role_overview(),
    )


def _weekly() -> WeeklyReport:
    return WeeklyReport(
        week_type=2,
        start_date="20260803",
        end_date="20260809",
        categories=(
            WeeklyReportCategory(
                category_name="完整资源分类",
                items=tuple(
                    WeeklyReportItem(
                        item_id=100 + index,
                        item_name=f"资源{index}-完整名称",
                        quality=index % 6,
                        total_num=str(index * 10),
                        icon=f"weekly://{index}",
                    )
                    for index in range(7)
                ),
            ),
            WeeklyReportCategory(category_name="空分类", items=()),
        ),
        role_overview=_role_overview(),
    )


def _calendar() -> CalendarSnapshot:
    return CalendarSnapshot(
        events=(
            CalendarEvent(
                title="活动甲",
                pic="calendar://a",
                start_at=datetime(2026, 8, 11, 9, 0, tzinfo=SHANGHAI),
                end_at=datetime(2026, 8, 12, 9, 0, tzinfo=SHANGHAI),
            ),
            CalendarEvent(
                title="活动乙",
                pic="",
                start_at=None,
                end_at=None,
            ),
        ),
    )


def _codes() -> CodeSnapshot:
    return CodeSnapshot(
        codes=("CODE-A", "CODE-B"),
        expires_at=datetime(2026, 8, 20, 23, 59, 59, tzinfo=SHANGHAI),
    )


async def _database_with_binding(
    tmp_path: Path,
    *,
    user_id: str = "user-1",
    uid: str = UID,
) -> AsyncDatabase:
    database = AsyncDatabase(tmp_path / "encyclopedia.sqlite3")
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


def _resources(tmp_path: Path) -> EncyclopediaResourceStore:
    wiki_role = tmp_path / "role.webp"
    wiki_weapon = tmp_path / "weapon.webp"
    wiki_spirit = tmp_path / "spirit.webp"
    guide_one = tmp_path / "guide-one.png"
    guide_two = tmp_path / "guide-two.png"
    for path, color in (
        (wiki_role, "red"),
        (wiki_weapon, "blue"),
        (wiki_spirit, "green"),
        (guide_one, "yellow"),
        (guide_two, "purple"),
    ):
        Image.new("RGBA", (31, 37), color).save(path)
    return EncyclopediaResourceStore(
        aliases=AliasCatalog(
            char_aliases={"角色甲": ("角色甲", "小甲")},
            weapon_aliases={"武器甲": ("武器甲", "大剑")},
        ),
        wiki_assets={
            ("role", "角色甲"): wiki_role,
            ("weapon", "武器甲"): wiki_weapon,
            ("spirit", "魔灵甲"): wiki_spirit,
        },
        guide_assets={
            "角色甲": (
                GuideAsset(provider="狩月庭攻略组", path=guide_one),
                GuideAsset(provider="猫冬", path=guide_two),
            ),
        },
    )


def test_resource_store_reads_runtime_alias_wiki_and_guide_assets(tmp_path: Path) -> None:
    """运行期资源根的索引必须支持别名、图鉴和按作者筛选的攻略。"""

    root = tmp_path / "resources"
    alias_root = root / "alias"
    alias_root.mkdir(parents=True)
    (alias_root / "char_alias.json").write_text(
        json.dumps({"角色甲": ["小甲"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (alias_root / "weapon_alias.json").write_text(
        json.dumps({"武器甲": ["大剑"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    role_wiki = root / "wiki" / "role" / "角色甲.webp"
    weapon_wiki = root / "wiki" / "weapon" / "武器甲.webp"
    guide = root / "guide" / "攻略组" / "角色甲-build.png"
    for path, color in ((role_wiki, "red"), (weapon_wiki, "blue"), (guide, "green")):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (31, 37), color).save(path)

    store = EncyclopediaResourceStore.from_root(root)

    assert store.wiki_asset("小甲") == ("role", role_wiki)
    assert store.wiki_asset("大剑") == ("weapon", weapon_wiki)
    assert store.guides_for("小甲", ("攻略组",)) == (
        GuideAsset(provider="攻略组", path=guide),
    )


@pytest.mark.asyncio
async def test_encyclopedia_renderer_marks_provided_and_missing_runtime_assets(tmp_path: Path) -> None:
    """周报和日历必须在图片 metadata 中显式区分提供素材与 placeholder。"""

    from src.utils.resource.RESOURCE_PATH import AVATAR_PATH, WEEKLY_ITEM_PATH

    root = tmp_path / "resources"
    weekly = root / "weekly_item" / "item_100.png"
    calendar = root / "calendar" / "a.png"
    for path, color in ((weekly, "yellow"), (calendar, "orange")):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (31, 37), color).save(path)
    avatar = AVATAR_PATH / "avatar_user-1.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), "red").save(avatar)
    for item_id in range(101, 107):
        cached = WEEKLY_ITEM_PATH / f"item_{item_id}.png"
        cached.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), "gray").save(cached)
    renderer = EncyclopediaRenderer(tmp_path / "rendered", EncyclopediaResourceStore.from_root(root))

    weekly_image = await renderer.render_weekly_report(
        _weekly(),
        actor=EventActor("user-1", "bot-1", "group-1"),
        uid=UID,
        uid_hidden=False,
    )
    calendar_image = await renderer.render_calendar(_calendar())

    assert (weekly_image.width, weekly_image.height) == (1200, 1370)
    assert any(
        item["kind"] == "font" and item["status"] == "fallback"
        for item in weekly_image.resources
    )
    assert any(
        item["kind"] == "weekly_item" and item["key"] == "100" and item["status"] == "provided"
        for item in weekly_image.resources
    )
    assert any(
        item["kind"] == "weekly_item" and item["key"] == "101" and item["status"] == "placeholder"
        for item in weekly_image.resources
    )
    assert any(
        item["kind"] == "calendar" and item["key"] == "活动甲" and item["status"] == "provided"
        for item in calendar_image.resources
    )
    assert any(
        item["kind"] == "calendar" and item["key"] == "活动乙" and item["status"] == "placeholder"
        for item in calendar_image.resources
    )


@pytest.mark.asyncio
async def test_stamina_renderer_uses_legacy_dnauid_canvas(tmp_path: Path) -> None:
    """便签必须复用原 DNAUID 的 2000x1100 卡片，而不是 rewrite 调试列表。"""

    from src.utils.resource.RESOURCE_PATH import AVATAR_PATH

    avatar = AVATAR_PATH / "avatar_user-1.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), "red").save(avatar)
    renderer = EncyclopediaRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(tmp_path / "resources"),
    )

    rendered = await renderer.render_stamina(
        _short_note(),
        actor=EventActor("user-1", "bot-1", "group-1"),
        uid=UID,
        uid_hidden=False,
    )

    with Image.open(rendered.path) as image:
        assert image.size == (2000, 1100)
        assert image.getpixel((1900, 500)) != (25, 31, 48, 255)


@pytest.mark.asyncio
async def test_weekly_renderer_uses_all_legacy_material_rows(tmp_path: Path) -> None:
    """周报按原素材卡模式动态增高，七个资源和空分类都必须保留。"""

    from src.utils.resource.RESOURCE_PATH import AVATAR_PATH, WEEKLY_ITEM_PATH

    avatar = AVATAR_PATH / "avatar_user-1.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), "red").save(avatar)
    for item_id in range(100, 107):
        cached = WEEKLY_ITEM_PATH / f"item_{item_id}.png"
        cached.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), "gray").save(cached)

    renderer = EncyclopediaRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(tmp_path / "resources"),
    )
    rendered = await renderer.render_weekly_report(
        _weekly(),
        actor=EventActor("user-1", "bot-1", "group-1"),
        uid=UID,
        uid_hidden=False,
    )

    with Image.open(rendered.path) as image:
        assert image.size == (1200, 1370)
        text = image.info["dnaby.text"]
    assert "资源6-完整名称" in text
    assert "空分类" in text


def test_weekly_legacy_card_truncates_only_the_visible_item_name() -> None:
    """固定卡片沿用服务端八字符显示规则，typed metadata 仍保存完整名称。"""

    from src.infrastructure.rendering.encyclopedia import weekly_item_display_name

    full_name = "超长资源名称测试项"
    assert weekly_item_display_name(full_name) == "超长资源名称测…"
    assert full_name == "超长资源名称测试项"


@pytest.mark.asyncio
async def test_calendar_renderer_uses_legacy_two_column_canvas(tmp_path: Path) -> None:
    """日历必须复用原 1200 宽横幅与双栏活动卡布局。"""

    root = tmp_path / "resources"
    for name, color in (("a.png", "orange"),):
        asset = root / "calendar" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (100, 100), color).save(asset)
    renderer = EncyclopediaRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore.from_root(root),
    )

    rendered = await renderer.render_calendar(
        _calendar(),
        actor=EventActor("actor-user", "bot-1", "group-1"),
        target_user_id="target-user",
    )

    with Image.open(rendered.path) as image:
        assert image.size == (1200, 1050)
        assert image.getpixel((1100, 800)) != (25, 31, 48, 255)
        assert "活动甲" in image.info["dnaby.text"]
    assert "活动乙" in image.info["dnaby.text"]


def test_legacy_role_adapter_preserves_role_id() -> None:
    from src.infrastructure.rendering.encyclopedia import _legacy_role_payload

    payload = _legacy_role_payload(_role_overview())
    assert payload["roleInfo"]["roleShow"]["roleId"] == "role-1"


def test_renderer_value_uses_asia_shanghai_for_aware_datetime() -> None:
    from src.infrastructure.rendering.encyclopedia import _value

    assert _value(datetime(2026, 8, 11, 1, 0, tzinfo=ZoneInfo("UTC"))) == "2026-08-11 09:00"


def test_renderer_write_round_trips_jpeg_quality_85_before_png(tmp_path: Path) -> None:
    renderer = EncyclopediaRenderer(tmp_path / "rendered", EncyclopediaResourceStore.from_root(tmp_path / "resources"))
    source = Image.new("RGBA", (3, 2))
    source.putdata([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255), (0, 255, 255, 255), (255, 0, 255, 255)])
    rendered = renderer._write(source, lines=[], resources=[], sections=[])
    with BytesIO() as expected_buffer:
        source.convert("RGB").save(expected_buffer, format="JPEG", quality=85)
        expected_buffer.seek(0)
        with Image.open(expected_buffer) as expected:
            expected_pixels = expected.convert("RGBA").tobytes()
    with Image.open(rendered.path) as actual:
        assert actual.convert("RGBA").tobytes() == expected_pixels


@pytest.mark.asyncio
async def test_calendar_is_global_and_ignores_mention_privacy(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path, user_id="target-user", uid=TARGET_UID)
    transport = FixtureEncyclopediaTransport(_short_note(), _weekly(), _calendar(), _codes())
    resources = _resources(tmp_path)
    calendar_asset = tmp_path / "calendar-a.png"
    Image.new("RGBA", (64, 64), "orange").save(calendar_asset)
    resources = EncyclopediaResourceStore(
        aliases=resources.aliases,
        wiki_assets=resources.wiki_assets,
        guide_assets=resources.guide_assets,
        calendar_assets={"calendar://a": calendar_asset},
    )
    service = EncyclopediaService(
        database,
        transport,
        PrivacyService(database, allow_mention_query=False),
        EncyclopediaRenderer(tmp_path / "rendered", resources),
        resources,
    )
    response = await service.calendar(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id="target-user",
        ),
    )
    assert isinstance(response, ImageResponse)
    assert transport.calls == [("calendar", None)]
    await database.dispose()


def _service(
    database: AsyncDatabase,
    transport: FixtureEncyclopediaTransport,
    resources: EncyclopediaResourceStore,
    tmp_path: Path,
) -> EncyclopediaService:
    return EncyclopediaService(
        database,
        transport,
        PrivacyService(database),
        EncyclopediaRenderer(tmp_path / "rendered", resources),
        resources,
        guide_providers=("all",),
    )


@pytest.mark.asyncio
async def test_stamina_and_weekly_images_preserve_full_typed_output(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    transport = FixtureEncyclopediaTransport(
        _short_note(),
        _weekly(),
        _calendar(),
        _codes(),
    )
    service = _service(database, transport, _resources(tmp_path), tmp_path)

    stamina = await service.stamina(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )
    weekly = await service.weekly_report(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"week_type": 2},
        ),
    )

    assert isinstance(stamina, ImageResponse)
    assert isinstance(weekly, ImageResponse)
    assert stamina.temporary is True
    assert weekly.temporary is True
    for response, expected_width, expected in (
        (stamina, 2000, ("资料玩家", "额外统计: 完整保留", "测试矿石", "完成材料")),
        (weekly, 1200, ("上周周报", "完整资源分类", "资源6-完整名称", "空分类")),
    ):
        with Image.open(Path(response.image)) as image:
            assert image.width == expected_width
            text = image.info["dnaby.text"]
            layout = json.loads(image.info["dnaby.layout"])
            resources = json.loads(image.info["dnaby.resources"])
        for value in expected:
            assert value in text
        assert layout["height"] > 0
        assert resources

    await database.dispose()


@pytest.mark.asyncio
async def test_mentioned_target_drives_credentials_uid_avatar_and_calendar_context(
    tmp_path: Path,
) -> None:
    """@查询必须沿用 resolved target，而不是命令发起者的头像或账号。"""

    from src.utils.resource.RESOURCE_PATH import AVATAR_PATH, WEEKLY_ITEM_PATH

    database = await _database_with_binding(
        tmp_path,
        user_id="target-user",
        uid=TARGET_UID,
    )
    for user_id, color in (("user-1", "red"), ("target-user", "blue")):
        avatar = AVATAR_PATH / f"avatar_{user_id}.png"
        avatar.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), color).save(avatar)
    for item_id in range(100, 107):
        item = WEEKLY_ITEM_PATH / f"item_{item_id}.png"
        item.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), "gray").save(item)

    calendar_root = tmp_path / "calendar-resources"
    for name, color in (("a.png", "orange"),):
        asset = calendar_root / "calendar" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), color).save(asset)
    transport = FixtureEncyclopediaTransport(
        _short_note(),
        _weekly(),
        _calendar(),
        _codes(),
        expected_uid=TARGET_UID,
        expected_credential_user_id="target-user",
    )
    service = _service(
        database,
        transport,
        EncyclopediaResourceStore.from_root(calendar_root),
        tmp_path,
    )
    request = EncyclopediaRequest(
        actor=EventActor("user-1", "bot-1", "group-1"),
        target_user_id="target-user",
    )

    stamina = await service.stamina(request)
    weekly = await service.weekly_report(
        EncyclopediaRequest(
            actor=request.actor,
            target_user_id=request.target_user_id,
            parameters={"week_type": 2},
        ),
    )
    calendar = await service.calendar(request)

    assert isinstance(stamina, ImageResponse)
    assert isinstance(weekly, ImageResponse)
    assert isinstance(calendar, ImageResponse)
    for response in (stamina, weekly):
        with Image.open(Path(response.image)) as image:
            pixel = image.convert("RGB").getpixel((160, 145))
            assert isinstance(pixel, tuple)
            assert pixel[2] >= 250 and pixel[0] <= 5 and pixel[1] <= 5
    assert transport.calls == [
        ("short_note", "target-user"),
        ("weekly", 2),
        ("calendar", None),
    ]
    await database.dispose()


@pytest.mark.asyncio
async def test_calendar_code_wiki_guide_and_alias_reads_keep_response_semantics(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    resources = _resources(tmp_path)
    calendar_asset = tmp_path / "calendar-a.png"
    Image.new("RGBA", (64, 64), "orange").save(calendar_asset)
    resources = EncyclopediaResourceStore(
        aliases=resources.aliases,
        wiki_assets=resources.wiki_assets,
        guide_assets=resources.guide_assets,
        calendar_assets={"calendar://a": calendar_asset},
    )
    transport = FixtureEncyclopediaTransport(_short_note(), _weekly(), _calendar(), _codes())
    service = _service(database, transport, resources, tmp_path)
    actor = EventActor("user-1", "bot-1", "group-1")

    calendar = await service.calendar(EncyclopediaRequest(actor=actor, target_user_id=None))
    codes = await service.codes(EncyclopediaRequest(actor=actor, target_user_id=None))
    wiki = await service.wiki(
        EncyclopediaRequest(actor=actor, target_user_id=None, parameters={"name": "小甲"}),
    )
    guide = await service.guide(
        EncyclopediaRequest(actor=actor, target_user_id=None, parameters={"char_name": "小甲"}),
    )
    alias = await service.alias_list(
        EncyclopediaRequest(
            actor=actor,
            target_user_id=None,
            parameters={"alias_type": "角色", "name": "小甲"},
        ),
    )
    all_alias = await service.alias_all_list(
        EncyclopediaRequest(actor=actor, target_user_id=None, text="武器列表"),
    )

    assert isinstance(calendar, ImageResponse)
    assert calendar.temporary is True
    with Image.open(Path(calendar.image)) as image:
        assert "活动甲" in image.info["dnaby.text"]
        assert "活动乙" in image.info["dnaby.text"]
    assert isinstance(codes, ChainResponse)
    assert any(isinstance(item, PlainTextResponse) and "CODE-A" in item.text for item in codes.components)
    assert isinstance(wiki, ImageResponse)
    assert Path(wiki.image).name == "role.webp"
    assert isinstance(guide, ChainResponse)
    assert any(isinstance(item, PlainTextResponse) and "狩月庭攻略组" in item.text for item in guide.components)
    assert sum(isinstance(item, ImageResponse) for item in guide.components) == 2
    assert isinstance(alias, PlainTextResponse)
    assert "小甲" in alias.text and "角色甲" in alias.text
    assert isinstance(all_alias, PlainTextResponse)
    assert "武器甲" in all_alias.text
    await database.dispose()


@pytest.mark.asyncio
async def test_guide_keeps_one_author_label_for_each_provider_group(tmp_path: Path) -> None:
    """同一作者的多张攻略图只应在组首显示一次作者文案。"""

    database = await _database_with_binding(tmp_path)
    guide_one = tmp_path / "guide-one.png"
    guide_two = tmp_path / "guide-two.png"
    Image.new("RGBA", (31, 37), "yellow").save(guide_one)
    Image.new("RGBA", (31, 37), "purple").save(guide_two)
    resources = EncyclopediaResourceStore(
        aliases=AliasCatalog(char_aliases={"角色甲": ("角色甲", "小甲")}),
        guide_assets={
            "角色甲": (
                GuideAsset(provider="攻略组", path=guide_one),
                GuideAsset(provider="攻略组", path=guide_two),
            ),
        },
    )
    transport = FixtureEncyclopediaTransport(_short_note(), _weekly(), _calendar(), _codes())
    service = _service(database, transport, resources, tmp_path)

    response = await service.guide(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
            parameters={"char_name": "小甲"},
        ),
    )

    assert isinstance(response, ChainResponse)
    assert [component.text for component in response.components if isinstance(component, PlainTextResponse)] == [
        "攻略作者：攻略组",
    ]
    assert [component.image for component in response.components if isinstance(component, ImageResponse)] == [
        str(guide_one),
        str(guide_two),
    ]
    await database.dispose()


@pytest.mark.asyncio
async def test_codes_keep_each_entry_expiry_when_provider_dates_differ(tmp_path: Path) -> None:
    """不同兑换码的截止时间必须逐项输出，不能只保留第一项。"""

    database = await _database_with_binding(tmp_path)
    transport = FixtureEncyclopediaTransport(
        _short_note(),
        _weekly(),
        _calendar(),
        CodeSnapshot(
            entries=(
                CodeEntry(
                    "CODE-A",
                    datetime(2026, 8, 20, 23, 59, 59, tzinfo=SHANGHAI),
                ),
                CodeEntry(
                    "CODE-B",
                    datetime(2026, 8, 21, 23, 59, 59, tzinfo=SHANGHAI),
                ),
            ),
        ),
    )
    service = _service(database, transport, _resources(tmp_path), tmp_path)

    response = await service.codes(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, ChainResponse)
    assert [component.text for component in response.components] == [
        "[DNA兑换码]",
        "CODE-A（有效期至：2026-08-20 23:59:59）",
        "CODE-B（有效期至：2026-08-21 23:59:59）",
    ]
    await database.dispose()


@pytest.mark.asyncio
async def test_encyclopedia_errors_are_visible_and_target_privacy_is_preserved(tmp_path: Path) -> None:
    database = await _database_with_binding(tmp_path)
    error = EncyclopediaTransportError(
        "server",
        resource="周报数据",
        detail="token=secret-encyclopedia",
    )
    transport = FixtureEncyclopediaTransport(_short_note(), _weekly(), _calendar(), _codes(), error=error)
    service = _service(database, transport, _resources(tmp_path), tmp_path)

    response = await service.stamina(
        EncyclopediaRequest(
            actor=EventActor("user-1", "bot-1", "group-1"),
            target_user_id=None,
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert "服务" in response.text
    assert "secret-encyclopedia" not in response.text
    assert transport.calls == [("short_note", "user-1")]
    await database.dispose()
