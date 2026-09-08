"""Task 07 主要渲染器资源解析接入的 Red 契约。

这些测试刻意只替换 legacy/T2I 绘制函数，验证渲染器本身是否把请求级资源解析器
传递到字体、纹理、角色/武器/面板和帮助资源边界；不会把网络或真实 T2I 服务带入
资源瘦身的最小回归。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import src.infrastructure.rendering.checkin as checkin_module
import src.infrastructure.rendering.encyclopedia as encyclopedia_module
import src.infrastructure.rendering.fonts as fonts_module
import src.infrastructure.rendering.help as help_module
import src.infrastructure.rendering.notices as notices_module
import src.infrastructure.rendering.player as player_module
from src.entry.event import EventActor
from src.infrastructure.rendering.checkin import CheckinRenderer
from src.infrastructure.rendering.encyclopedia import EncyclopediaRenderer
from src.infrastructure.rendering.notices import NoticesRenderer
from src.infrastructure.rendering.player import PlayerRenderer, ResourceMap
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.resolver import ResolvedAsset
from src.modules.checkin.contracts import (
    CheckinCalendarData,
    SignCalendar,
    SignPeriod,
)
from src.modules.encyclopedia.contracts import (
    CalendarEvent,
    CalendarSnapshot,
    WeeklyReport,
    WeeklyReportCategory,
    WeeklyReportItem,
)
from src.modules.notices.contracts import AnnPost, AnnSnapshot
from src.modules.player.contracts import (
    RoleAttribute,
    RoleDetail,
    RoleItem,
    RoleOverview,
    WeaponItem,
)


@dataclass
class RecordingResolver:
    """只记录逻辑 key 的请求级 resolver；所有素材均模拟为缺失。"""

    generation: str = "generation-a"

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve(self, logical_key: str) -> ResolvedAsset:
        self.calls.append((self.generation, logical_key))
        return ResolvedAsset(
            path=None,
            source="none",
            status="missing",
            incomplete=True,
        )


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (240, 240, 240)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _overview_fixture() -> RoleOverview:
    return RoleOverview(
        role_id="role-1",
        role_name="测试角色",
        level=42,
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


def _missing_key(resolver: RecordingResolver, *fragments: str) -> bool:
    return any(
        all(fragment in logical_key for fragment in fragments)
        for _, logical_key in resolver.calls
    )


def _assert_missing_keys(resolver: RecordingResolver, *patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        assert _missing_key(resolver, *pattern), (
            f"请求级 resolver 未解析逻辑资源 key {pattern!r}；"
            f"实际请求={resolver.calls!r}"
        )


def _attach_resolver(renderer: Any, resolver: RecordingResolver) -> None:
    """通过最小注入 seam 给现有 renderer 绑定请求级 resolver。"""

    renderer.asset_resolver = resolver


def test_runtime_font_falls_back_when_bundled_font_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完整本地字体被移除后，启动加载仍应返回可用字体对象。"""

    monkeypatch.setattr(fonts_module, "BUNDLED_FONT_PATH", tmp_path / "missing.ttf")

    font = fonts_module.load_runtime_font(size=16)

    assert font.getbbox("DNA") is not None


@pytest.mark.asyncio
async def test_player_overview_uses_resolver_for_role_and_weapon_and_refreshes_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """角色/武器来源必须走当前 snapshot resolver，换 generation 后不能复用旧视图。"""

    async def fake_overview(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(player_module, "draw_role_info_card_core", fake_overview)
    resolver = RecordingResolver()
    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    _attach_resolver(renderer, resolver)

    await renderer.render_overview(_overview_fixture(), uid="1234567890123")
    resolver.generation = "generation-b"
    await renderer.render_overview(_overview_fixture(), uid="1234567890123")

    _assert_missing_keys(
        resolver,
        ("font.",),
        ("role_avatar", "101"),
        ("weapon", "201"),
    )
    assert {generation for generation, _ in resolver.calls} == {
        "generation-a",
        "generation-b",
    }


@pytest.mark.asyncio
async def test_player_detail_uses_resolver_for_paint_and_panel_and_marks_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """角色详情缺少立绘/面板时应简化渲染，并明确标记 incomplete。"""

    async def fake_detail(*_: object, **__: object) -> tuple[bytes, None]:
        return _jpeg_bytes(), None

    monkeypatch.setattr(player_module, "_draw_role_detail_card", fake_detail)
    resolver = RecordingResolver()
    renderer = PlayerRenderer(tmp_path / "rendered", ResourceMap())
    _attach_resolver(renderer, resolver)
    detail = RoleDetail(
        attribute=RoleAttribute(),
        char_id=101,
        char_name="角色甲",
        level=80,
    )

    rendered = await renderer.render_detail(detail, uid="1234567890123")

    assert rendered.incomplete is True
    _assert_missing_keys(
        resolver,
        ("font.",),
        ("role_paint", "101"),
        ("panel", "101"),
    )


@pytest.mark.asyncio
async def test_encyclopedia_missing_weekly_and_calendar_assets_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """百科周报与活动日历的纹理缺失时仍生成结果，并保留不完整状态。"""

    async def fake_weekly(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    async def fake_calendar(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(encyclopedia_module, "_draw_weekly_report_card", fake_weekly)
    monkeypatch.setattr(encyclopedia_module, "_draw_calendar_card_bytes", fake_calendar)
    resolver = RecordingResolver()
    renderer = EncyclopediaRenderer(
        tmp_path / "rendered", EncyclopediaResourceStore()
    )
    _attach_resolver(renderer, resolver)
    weekly = WeeklyReport(
        week_type=1,
        start_date="2026-09-01",
        end_date="2026-09-07",
        categories=(
            WeeklyReportCategory(
                category_name="材料",
                items=(WeeklyReportItem(item_id=701, item_name="材料甲"),),
            ),
        ),
    )
    calendar = CalendarSnapshot(
        events=(
            CalendarEvent(
                title="活动甲",
                pic="missing-event.png",
                start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                end_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            ),
        ),
    )

    weekly_rendered = await renderer.render_weekly_report(weekly, uid="1234567890123")
    calendar_rendered = await renderer.render_calendar(calendar)

    _assert_missing_keys(
        resolver,
        ("font.",),
        ("weekly", "701"),
        ("calendar", "missing-event.png"),
    )
    assert weekly_rendered.incomplete is True
    assert calendar_rendered.incomplete is True


@pytest.mark.asyncio
async def test_checkin_missing_textures_are_placeholder_and_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """签到日历缺少本地纹理时不得因硬编码字体/背景路径启动失败。"""

    async def fake_calendar(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(checkin_module, "_draw_sign_calendar", fake_calendar)
    resolver = RecordingResolver()
    renderer = CheckinRenderer(tmp_path / "rendered", EncyclopediaResourceStore())
    _attach_resolver(renderer, resolver)
    data = CheckinCalendarData(
        calendar=SignCalendar(
            signin_time=1,
            period=SignPeriod(
                period_id=1,
                name="周期甲",
                over_days=7,
                start_date=0,
                end_date=0,
            ),
        ),
        role_overview=_overview_fixture(),
    )

    rendered = await renderer.render_calendar(
        data,
        actor=EventActor("user-1", "bot-1", "group-1"),
        target_user_id="user-1",
        uid_hidden=False,
    )

    _assert_missing_keys(resolver, ("font.",), ("texture.sign",))
    assert rendered.incomplete is True


@pytest.mark.asyncio
async def test_notices_missing_font_and_textures_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """密函/公告绘制应使用 resolver，并将缺失素材显式带入结果状态。"""

    async def fake_ann_list(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(notices_module, "draw_ann_list_img", fake_ann_list)
    resolver = RecordingResolver()
    renderer = NoticesRenderer(tmp_path / "rendered", EncyclopediaResourceStore())
    _attach_resolver(renderer, resolver)

    rendered = await renderer.render_ann_list(
        AnnSnapshot(posts=(AnnPost(post_id="1001", title="公告甲"),)),
    )

    _assert_missing_keys(resolver, ("font.",), ("texture.ann",))
    assert rendered.incomplete is True


@pytest.mark.asyncio
async def test_help_accepts_resolver_for_font_and_texture_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帮助卡片的字体、背景和图标必须能从 resolver 获取并支持缺失降级。"""

    async def fake_render(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(
        help_module,
        "_load_help_data",
        lambda: {"基础": {"desc": "", "data": [{"name": "状态", "eg": "状态"}]}},
    )
    monkeypatch.setattr(help_module, "image_data_uri", lambda *_args, **_kwargs: "image")
    monkeypatch.setattr(help_module, "font_data_uri", lambda *_args, **_kwargs: "font")
    monkeypatch.setattr(help_module._RENDERER, "render", fake_render)
    resolver = RecordingResolver()

    rendered = await help_module.get_help(prefix="", asset_resolver=resolver)

    assert rendered == _jpeg_bytes()
    _assert_missing_keys(resolver, ("font.help",), ("texture.help",))
