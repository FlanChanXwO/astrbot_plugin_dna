"""静态资源渲染契约 smoke。

使用 fake snapshot（自绘 PNG / 占位 ttf）验证 StaticAssetResolver 契约、
renderer fallback 与 generation lease 三个稳定场景：

- Case 1：完整 fake snapshot → 渲染成功且 incomplete=False。
- Case 2：无 snapshot → placeholder 降级、incomplete=True、不崩溃。
- Case 3：请求中切换 generation → 已固定的 resolver 仍读旧 generation。

本文件不模拟完整 dna-resource，也不作为生产素材齐全性的证明；
生产素材 parity 由合并前对 dna-resource/main 的真实验证承担。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.infrastructure.rendering import ResourceMap
from src.infrastructure.rendering.checkin import CheckinRenderer
from src.infrastructure.rendering.encyclopedia import _draw_calendar_card_bytes
from src.infrastructure.rendering.notices import NoticesRenderer
from src.infrastructure.rendering.player import PlayerRenderer
from src.infrastructure.rendering.static_assets import (
    BOOTSTRAP_RELATIVE_ALLOWLIST,
    StaticAssetResolver,
    static_open_image,
)
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.generation import (
    ResourceManifest,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)
from src.modules.checkin.contracts import CheckinCalendarData, SignCalendar, SignPeriod
from src.modules.notices.contracts import MhInstance, MhSection, MhSnapshot
from src.modules.player.contracts import RoleOverview

BOOTSTRAP_TEXTURE_DIR = Path(__file__).parents[1] / "src" / "utils" / "texture2d"

_PLAYER_STATICS = (
    "textures/common/bg1.jpg",
    "textures/common/bg2.jpg",
    "textures/role/bg/bg1.png",
    "textures/role/bg/bg4.png",
    "textures/role/bg/bg5.png",
    "textures/role/info_bar.png",
    "textures/role/div_bg.png",
    "textures/role/item_fg.png",
    "textures/role/item_mask.png",
    "textures/role/title_bg.jpg",
    "textures/role/title_mask.png",
)


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (200, 60, 60, 255)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _write_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 120, 200)).save(buffer, format="JPEG")
    path.write_bytes(buffer.getvalue())


def _build_snapshot(root: Path, *, generation: str) -> Path:
    """构造一个覆盖核心卡片所需静态素材的 verified generation 目录。"""

    for relative in _PLAYER_STATICS:
        (_write_jpeg if relative.endswith(".jpg") else _write_png)(root / relative)
    for name in ("bar", "item_BG", "green", "red", "line"):
        _write_png(root / "textures" / "sign" / f"{name}.png")
    for name in ("bg1", "bg2", "bg3"):
        _write_jpeg(root / "textures" / "mh" / f"{name}.jpg")
    for name in ("bar", "card", "refresh_time", "title", "mh_role", "mh_weapon"):
        _write_png(root / "textures" / "mh" / f"{name}.png")
    for name in ("bg", "banner_mask", "banner_frame", "event_bg", "bar", "time_icon"):
        _write_png(root / "calendar" / f"{name}.png")
    _write_jpeg(root / "calendar" / "bg.jpg")
    fonts = root / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "dna_fonts.ttf").write_bytes(b"ttf")
    (fonts / "arial-unicode-ms-bold.ttf").write_bytes(b"ttf")
    manifest = {
        "format_version": 1,
        "required_dirs": ["fonts", "images"],
        "resource_version": "smoke",
    }
    import json

    (root / "resource_manifest.json").write_text(json.dumps(manifest))
    del generation
    return root


def _make_coordinator_with_snapshot(
    tmp_path: Path, generation_dir: Path, commit_sha: str
) -> ResourceSnapshotCoordinator:
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "repository",
        generations_root=tmp_path / "generations",
    )
    coordinator._current = ResourceSnapshot(
        commit_sha=commit_sha,
        root=generation_dir,
        manifest=ResourceManifest(
            format_version=1,
            required_dirs=("fonts",),
            resource_version="smoke",
        ),
        player_resources=ResourceMap(),
        encyclopedia_resources=EncyclopediaResourceStore(),
    )
    return coordinator


def _stub_avatar(monkeypatch) -> None:
    """屏蔽头像下载，避免测试间共享的 httpx 连接池跨事件循环复用。"""

    from PIL import Image

    from src.infrastructure.rendering import payloads

    async def _fake_event_avatar(*_args, **_kwargs):
        return Image.new("RGBA", (16, 16), (90, 120, 200, 255))

    monkeypatch.setattr(payloads, "get_event_avatar", _fake_event_avatar)
    import src.utils.image as image_utils

    async def _fake_avatar_img(*_args, **_kwargs):
        return Image.new("RGBA", (16, 16), (60, 160, 90, 255))

    monkeypatch.setattr(payloads, "get_avatar_img", _fake_avatar_img)
    monkeypatch.setattr(image_utils, "get_avatar_img", _fake_avatar_img)


def _actor() -> SimpleNamespace:
    return SimpleNamespace(
        user_id="10000", bot_id="bot", group_id="", unified_msg_origin=""
    )


def test_case1_full_snapshot_renders_core_cards_incomplete_false(
    tmp_path, monkeypatch
) -> None:
    _stub_avatar(monkeypatch)
    generation = _build_snapshot(tmp_path / "gen-a", generation="a" * 40)
    resolver = StaticAssetResolver(
        snapshot_root=generation,
        bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
        bootstrap_relative_allowlist=BOOTSTRAP_RELATIVE_ALLOWLIST,
    ).pinned(generation, generation_id="a" * 40)

    # 玩家角色总览
    player_renderer = PlayerRenderer(
        tmp_path / "rendered-player", ResourceMap.from_root(generation)
    )
    player_renderer.static_asset_resolver = resolver
    overview = RoleOverview.model_construct(
        role_id="10001", role_name="角色", level=60
    )
    result = asyncio.run(
        player_renderer.render_overview(
            overview,
            uid="123456",
            actor=_actor(),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert result.path.is_file()
    assert result.incomplete is False

    # 签到日历
    checkin_renderer = CheckinRenderer(
        tmp_path / "rendered-checkin", EncyclopediaResourceStore()
    )
    checkin_renderer.static_asset_resolver = resolver
    calendar = CheckinCalendarData(
        calendar=SignCalendar(
            today_signed=True,
            signin_time=2,
            period=SignPeriod(
                period_id=1, name="周期", over_days=7, start_date=0, end_date=7
            ),
        ),
        total_sign_in_days=3,
        role_overview=RoleOverview.model_construct(role_id="10001", role_name="角色"),
    )
    checkin_result = asyncio.run(
        checkin_renderer.render_calendar(
            calendar,
            actor=_actor(),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert checkin_result.path.is_file()
    assert checkin_result.incomplete is False

    # 密函卡片
    notices_renderer = NoticesRenderer(
        tmp_path / "rendered-notices",
        EncyclopediaResourceStore(font_path=generation / "fonts" / "dna_fonts.ttf"),
    )
    notices_renderer.static_asset_resolver = resolver
    snapshot = MhSnapshot(
        sections=(
            MhSection(
                mh_type="role",
                type_name="角色",
                instances=(MhInstance(instance_id=1, name="委托"),),
            ),
        )
    )
    mh_result = asyncio.run(notices_renderer.render_mh(snapshot, simple_image=False))
    assert mh_result.path.is_file()
    assert mh_result.incomplete is False

    # 活动日历
    from src.infrastructure.rendering.encyclopedia import CalendarContent

    calendar_bytes = asyncio.run(
        _draw_calendar_card_bytes(
            [CalendarContent(title="活动", pic="", start_time="", end_time="")],
            static_asset_resolver=resolver,
            static_records=[],
        )
    )
    assert calendar_bytes


def test_case2_without_snapshot_falls_back_incomplete(
    tmp_path, monkeypatch
) -> None:
    _stub_avatar(monkeypatch)
    resolver = StaticAssetResolver(
        bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
        bootstrap_relative_allowlist=BOOTSTRAP_RELATIVE_ALLOWLIST,
    )
    checkin_renderer = CheckinRenderer(
        tmp_path / "rendered-checkin", EncyclopediaResourceStore()
    )
    checkin_renderer.static_asset_resolver = resolver
    calendar = CheckinCalendarData(
        calendar=SignCalendar(
            today_signed=True,
            signin_time=2,
            period=SignPeriod(
                period_id=1, name="周期", over_days=7, start_date=0, end_date=7
            ),
        ),
        total_sign_in_days=3,
        role_overview=RoleOverview.model_construct(role_id="10001", role_name="角色"),
    )
    result = asyncio.run(
        checkin_renderer.render_calendar(
            calendar,
            actor=_actor(),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert result.path.is_file()
    # 本地 bootstrap 装饰图可覆盖 common 纹理，但 sign 纹理与字体已外置，
    # 缺 snapshot 时必然走 placeholder/incomplete。
    assert result.incomplete is True


def test_case3_request_keeps_generation_across_switch(tmp_path) -> None:
    """请求开始后 generation 切换，已固定的 resolver 仍读旧 generation。"""

    generation_a = _build_snapshot(tmp_path / "gen-a", generation="a" * 40)
    generation_b = _build_snapshot(tmp_path / "gen-b", generation="b" * 40)
    coordinator = _make_coordinator_with_snapshot(
        tmp_path, generation_a, "a" * 40
    )
    with coordinator.bind_static_asset_resolver(
        StaticAssetResolver(
            coordinator=coordinator, bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR
        )
    ) as pinned:
        # 请求进行中发布 generation B。
        coordinator._current = ResourceSnapshot(
            commit_sha="b" * 40,
            root=generation_b,
            manifest=ResourceManifest(
                format_version=1,
                required_dirs=("fonts",),
                resource_version="smoke",
            ),
            player_resources=ResourceMap(),
            encyclopedia_resources=EncyclopediaResourceStore(),
        )
        assert pinned.generation_id == "a" * 40
        resolved = pinned.resolve_relative("textures/role/info_bar.png")
        assert resolved.path == generation_a / "textures" / "role" / "info_bar.png"
    # 下一次请求开始读取 B。
    with coordinator.bind_static_asset_resolver(
        StaticAssetResolver(coordinator=coordinator)
    ) as pinned_b:
        assert pinned_b.generation_id == "b" * 40


def test_missing_static_assets_force_incomplete(tmp_path) -> None:
    """任一正式静态素材缺失都必须让渲染结果 incomplete=True。"""

    generation = _build_snapshot(tmp_path / "gen", generation="a" * 40)
    # 构造素材缺口：签到条、密函类型图标、日历 banner、周报品质角标。
    (generation / "textures" / "sign" / "bar.png").unlink()
    (generation / "textures" / "mh" / "mh_role.png").unlink()
    (generation / "calendar" / "banner_mask.png").unlink()
    # 周报品质角标不在 fake snapshot 清单内，缺 q2.png 即代表缺失。
    resolver = StaticAssetResolver(
        snapshot_root=generation,
        bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
        bootstrap_relative_allowlist=BOOTSTRAP_RELATIVE_ALLOWLIST,
    ).pinned(generation, generation_id="a" * 40)

    # 签到日历：缺 sign/bar.png。
    checkin_renderer = CheckinRenderer(
        tmp_path / "rendered-checkin", EncyclopediaResourceStore()
    )
    checkin_renderer.static_asset_resolver = resolver
    checkin_result = asyncio.run(
        checkin_renderer.render_calendar(
            CheckinCalendarData(
                calendar=SignCalendar(
                    today_signed=True,
                    signin_time=2,
                    period=SignPeriod(
                        period_id=1, name="周期", over_days=7, start_date=0, end_date=7
                    ),
                ),
                total_sign_in_days=3,
                role_overview=RoleOverview.model_construct(
                    role_id="10001", role_name="角色"
                ),
            ),
            actor=_actor(),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert checkin_result.incomplete is True

    # 密函：缺 mh_role.png。
    notices_renderer = NoticesRenderer(
        tmp_path / "rendered-notices", EncyclopediaResourceStore()
    )
    notices_renderer.static_asset_resolver = resolver
    mh_result = asyncio.run(
        notices_renderer.render_mh(
            MhSnapshot(
                sections=(
                    MhSection(
                        mh_type="role",
                        type_name="角色",
                        instances=(MhInstance(instance_id=1, name="委托"),),
                    ),
                )
            ),
            simple_image=False,
        )
    )
    assert mh_result.incomplete is True

    # 日历 banner：缺 banner_mask.png 时资源记录必须暴露 incomplete。
    from src.infrastructure.rendering.encyclopedia import _load_banner

    calendar_records: list[dict[str, str]] = []
    asyncio.run(_load_banner(1050, resolver, calendar_records))
    assert any(
        record.get("key") == "texture.calendar.banner_mask"
        and record.get("incomplete") == "true"
        for record in calendar_records
    )

    # 周报品质角标：缺 q2.png 时记录必须暴露 incomplete。
    from src.infrastructure.rendering.encyclopedia import _weekly_item_payload

    item = SimpleNamespace(item_id=1, item_name="道具", icon="", quality=2, total_num="1")
    weekly_records: list[dict[str, str]] = []
    payload = asyncio.run(
        _weekly_item_payload(
            item,
            {1: generation / "weekly_item" / "item_101.png"}
            if (generation / "weekly_item" / "item_101.png").exists()
            else None,
            static_asset_resolver=resolver,
            static_records=weekly_records,
            weekly_item_cache_dir=tmp_path / "weekly-cache",
        )
    )
    assert payload["quality"] == ""
    assert any(
        record.get("key") == "texture.weekly_report.quality_q2"
        and record.get("incomplete") == "true"
        for record in weekly_records
    )


def test_static_open_image_writes_records(tmp_path: Path) -> None:
    """static_open_image 的 key/records 参数保证 placeholder 参与 incomplete 判定。"""

    present_records: list[dict[str, str]] = []
    static_open_image(
        StaticAssetResolver(
            snapshot_root=_build_snapshot(tmp_path / "full", generation="a" * 40),
            bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
        ),
        "textures/sign/bar.png",
        size=(4, 4),
        label="签到",
        key="texture.sign.bar",
        records=present_records,
    )
    assert present_records[0]["incomplete"] == "false"

    missing_records: list[dict[str, str]] = []
    static_open_image(
        StaticAssetResolver(
            snapshot_root=tmp_path / "empty",
            bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
        ),
        "textures/stamina/icon1.png",
        size=(4, 4),
        label="便签",
        key="texture.stamina.icon1",
        records=missing_records,
    )
    assert missing_records[0]["incomplete"] == "true"
