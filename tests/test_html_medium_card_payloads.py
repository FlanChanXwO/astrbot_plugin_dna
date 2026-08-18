import base64
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

import src.rendering.payloads as profile_payloads
from src.infrastructure.rendering.encyclopedia import (
    TEXT_PATH,
    CalendarContent,
    _calendar_background,
    _event_payload,
    _load_banner,
    _progress_ratio,
)
from src.infrastructure.rendering.notices import _mh_payload
from src.utils.api.model import DNARoleForToolInstance, DNARoleForToolInstanceInfo
from src.utils.image_utils import crop_center_img
from src.utils.session import EventContext


def test_mh_payload_keeps_dynamic_instances_and_subscription_state() -> None:
    result = _mh_payload(
        [
            DNARoleForToolInstanceInfo(
                mh_type="role",
                instances=[DNARoleForToolInstance(id=1, name="长密函名称")],
            )
        ],
        ["角色:长密函名称"],
    )

    assert result[0]["type_name"] == "角色"
    assert result[0]["instances"] == [{"name": "长密函名称", "subscribed": True}]


def test_stamina_ratio_handles_empty_total_and_caps_visual_progress() -> None:
    assert _progress_ratio(0, 0) == 0
    assert _progress_ratio(2, 4) == 0.5
    assert _progress_ratio(8, 4) == 1


def test_calendar_payload_preserves_long_title_and_date_state() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    event = CalendarContent(
        title="一个不应被数据层截断的活动标题",
        pic="moling.png",
        start_time="2026-08-16 00:00",
        end_time="2026-08-18 00:00",
    )

    payload = _event_payload(event, datetime(2026, 8, 17, 0, 0, tzinfo=tz))

    assert payload["title"] == event.title
    assert payload["status"] == "进行中"
    assert payload["progress"] == 0.5


@pytest.mark.asyncio
async def test_calendar_banner_matches_legacy_rgba_mask_composition() -> None:
    data_uri = await _load_banner(2580)
    actual = Image.open(BytesIO(base64.b64decode(data_uri.split(",", 1)[1]))).convert("RGBA")

    expected = _calendar_background(2580).crop((0, 150, 1200, 750))
    with Image.open(TEXT_PATH / "banner_bg.webp") as opened:
        banner = crop_center_img(opened.convert("RGBA").resize((1200, 675)), 1200, 600)
    with Image.open(TEXT_PATH / "banner_mask.png") as opened:
        mask = opened.getchannel("A")
    with Image.open(TEXT_PATH / "banner_frame.png") as opened:
        frame = opened.convert("RGBA")
    expected.paste(banner, (0, 0), mask)
    expected.alpha_composite(frame)

    assert actual.tobytes() == expected.tobytes()


@pytest.mark.asyncio
async def test_profile_header_preserves_default_avatar_fallback_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_ids: list[str] = []

    async def fail_event_avatar(*_: object, **__: object) -> Image.Image:
        raise OSError("avatar unavailable")

    async def fake_avatar(char_id: str) -> Image.Image:
        requested_ids.append(char_id)
        return Image.new("RGBA", (1, 1))

    monkeypatch.setattr(profile_payloads, "get_event_avatar", fail_event_avatar)
    monkeypatch.setattr(profile_payloads, "get_avatar_img", fake_avatar)
    monkeypatch.setattr(profile_payloads, "pil_image_data_uri", lambda _: "data:image/png;base64,AA==")
    ctx = EventContext(user_id="sender", at="original")

    payload = await profile_payloads.build_profile_header(
        ctx,
        "role-uid",
        "角色名",
        avatar_user_id="target",
        uid_hidden=True,
    )

    assert requested_ids == ["5101"]
    assert ctx.at == "original"
    assert payload["uid"] is None
    assert str(payload["avatar_frame"]).startswith("data:image/png;base64,")
    assert str(payload["level_background"]).startswith("data:image/png;base64,")
    assert str(payload["stats_background"]).startswith("data:image/png;base64,")
