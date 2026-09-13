"""Checkin 渲染的静态资源解析契约。

插件本地大型纹理/字体已外置到 dna-resource；签到日历必须经
StaticAssetResolver 从 verified snapshot 取材，缺失时降级为 placeholder
并标记 incomplete，而不是读取已删除的 src/resources 路径。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.infrastructure.rendering.checkin import CheckinRenderer
from src.infrastructure.rendering.static_assets import StaticAssetResolver
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.modules.checkin.contracts import CheckinCalendarData, SignCalendar, SignPeriod
from src.modules.player.contracts import RoleHeader

BOOTSTRAP_TEXTURE_DIR = Path(__file__).parents[1] / "src" / "utils" / "texture2d"


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (200, 60, 60, 255)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _snapshot(tmp_path: Path) -> Path:
    snapshot = tmp_path / "generation"
    for name in ("bar", "item_BG", "green", "red", "line"):
        _write_png(snapshot / "textures" / "sign" / f"{name}.png")
    fonts = snapshot / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "dna_fonts.ttf").write_bytes(b"ttf")
    return snapshot


def _stub_avatar(monkeypatch) -> None:
    """屏蔽头像下载，避免测试间共享的 httpx 连接池跨事件循环复用。"""

    from PIL import Image

    import src.infrastructure.rendering.payloads as payloads

    async def _fake_event_avatar(*_args, **_kwargs):
        return Image.new("RGBA", (16, 16), (90, 120, 200, 255))

    monkeypatch.setattr(payloads, "get_event_avatar", _fake_event_avatar)
    import src.utils.image as image_utils

    async def _fake_avatar_img(*_args, **_kwargs):
        return Image.new("RGBA", (16, 16), (60, 160, 90, 255))

    monkeypatch.setattr(payloads, "get_avatar_img", _fake_avatar_img)
    monkeypatch.setattr(image_utils, "get_avatar_img", _fake_avatar_img)


def _calendar_data() -> CheckinCalendarData:
    return CheckinCalendarData(
        calendar=SignCalendar(
            today_signed=True,
            signin_time=2,
            period=SignPeriod(period_id=1, name="周期", over_days=7, start_date=0, end_date=7),
        ),
        total_sign_in_days=3,
        role_overview=RoleHeader(
            role_id="101",
            role_name="测试角色",
            level=60,
            params=[],
        ),
    )


def test_checkin_calendar_renders_from_verified_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    _stub_avatar(monkeypatch)
    resolver = StaticAssetResolver(
        snapshot_root=_snapshot(tmp_path),
        bootstrap_texture_dir=BOOTSTRAP_TEXTURE_DIR,
    )
    renderer = CheckinRenderer(tmp_path / "rendered", EncyclopediaResourceStore())
    renderer.static_asset_resolver = resolver

    rendered = asyncio.run(
        renderer.render_calendar(
            _calendar_data(),
            actor=SimpleNamespace(
                user_id="10000", bot_id="bot", group_id="", unified_msg_origin=""
            ),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert rendered.path.is_file()
    assert rendered.incomplete is False
    keys = {record.get("key") for record in rendered.resources}
    assert "texture.sign.bar" in keys
    assert "font.dna_fonts" in keys


def test_checkin_calendar_falls_back_without_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    _stub_avatar(monkeypatch)
    renderer = CheckinRenderer(tmp_path / "rendered", EncyclopediaResourceStore())
    rendered = asyncio.run(
        renderer.render_calendar(
            _calendar_data(),
            actor=SimpleNamespace(
                user_id="10000", bot_id="bot", group_id="", unified_msg_origin=""
            ),
            target_user_id="10000",
            uid_hidden=True,
        )
    )
    assert rendered.path.is_file()
    assert rendered.incomplete is True
