"""Goal 4 / Task 06：签到 T2I 原始图片直出契约。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from src.entry.event import EventActor
from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.infrastructure.rendering import checkin as checkin_module
from src.infrastructure.rendering.checkin import CheckinRenderer
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.modules.checkin.contracts import (
    CheckinCalendarData,
    DayAward,
    SignCalendar,
    SignPeriod,
    SignRoleInfo,
    TaskProcess,
)
from src.modules.player.contracts import RoleOverview


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (41, 23), "#4979a8").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def test_checkin_renderer_publishes_original_t2i_jpeg(monkeypatch, tmp_path: Path) -> None:
    payload = _jpeg_bytes()

    async def fake_draw(*_args, **_kwargs) -> bytes:
        return payload

    monkeypatch.setattr(checkin_module, "_draw_sign_calendar", fake_draw)
    data = CheckinCalendarData(
        calendar=SignCalendar(
            signin_time=2,
            day_awards=(DayAward(1, 9, 1, "奖励", 5),),
            period=SignPeriod(9, "周期", 1, 0, 0),
            role_info=SignRoleInfo("101", "角色", 60),
        ),
        tasks=TaskProcess(),
        total_sign_in_days=8,
        role_overview=RoleOverview(role_id="101", role_name="角色", level=60),
    )
    renderer = CheckinRenderer(
        tmp_path / "rendered",
        EncyclopediaResourceStore(tmp_path / "resources"),
    )

    rendered = __import__("asyncio").run(
        renderer.render_calendar(
            data,
            actor=EventActor("user", "bot", "group"),
            target_user_id="user",
            uid_hidden=True,
        )
    )

    assert rendered.path.suffix == ".jpg"
    assert rendered.path.read_bytes() == payload
    assert rendered.media_type == "image/jpeg"
    artifact = read_rendered_artifact(rendered.path)
    assert artifact.metadata["dnaby.text"] == "角色\n社区累计签到: 8\n游戏累计签到: 2"


def test_help_use_case_publishes_original_t2i_jpeg_with_sidecar(tmp_path: Path) -> None:
    from src.entry.commands import CommandRegistry, CommandRequest
    from src.modules.help import help_use_case

    payload = _jpeg_bytes()

    async def fake_help(_prefix: str) -> bytes:
        return payload

    request = CommandRequest(
        command_id="help",
        text="kk帮助",
        parameters={},
        services={"rendered_root": tmp_path / "rendered", "help_renderer": fake_help},
        matched_prefix="kk",
    )
    response = __import__("asyncio").run(help_use_case(request, CommandRegistry(())))

    assert Path(response.image).read_bytes() == payload
    assert response.sidecar is not None
    assert response.manifest is not None
    assert read_rendered_artifact(response.image).data == payload
