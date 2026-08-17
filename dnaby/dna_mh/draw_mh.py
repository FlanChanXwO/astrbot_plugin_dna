import random
from datetime import timedelta
from pathlib import Path

from astrbot.api import logger

from ..rendering import HtmlRenderer, RenderSpec, font_data_uri, image_data_uri
from ..utils import get_datetime
from ..utils.api.mh_map import get_mh_type_name
from ..utils.api.model import DNARoleForToolInstanceInfo
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.msgs.notify import send_dna_notify
from ..utils.session import EventContext, Sender
from .cache_mh import get_mh_result
from .subscribe_mh import get_mh_subscribe_list

TEXT_PATH = Path(__file__).parent / "texture2d"
bg_list = ["bg1.jpg", "bg2.jpg", "bg3.jpg"]
_RENDERER = HtmlRenderer()


def is_simple_picture() -> bool:
    from ..dna_config.dna_config import DNAConfig

    return DNAConfig.get_config("MHSimplePicture").data


async def draw_mh(sender: Sender, ctx: EventContext):
    now = get_datetime()
    next_refresh = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    remaining_seconds = int((next_refresh - now).total_seconds())

    mh_result = await get_mh_result(int(next_refresh.timestamp()))
    if not mh_result:
        await send_dna_notify(sender, ctx, "未找到有效的密函数据")
        return

    mh_list, _ = await get_mh_subscribe_list(sender, ctx, ctx.user_id)
    if is_simple_picture():
        card = await draw_mh_simple(mh_result, remaining_seconds, mh_list)
    else:
        card = await draw_mh_card(mh_result, remaining_seconds, mh_list)
    return await sender.send(card)


def _is_subscribed(instance_name: str, type_name: str, subscribe_list: list[str] | None) -> bool:
    return bool(subscribe_list and (instance_name in subscribe_list or f"{type_name}:{instance_name}" in subscribe_list))


def _mh_payload(
    mh_result: list[DNARoleForToolInstanceInfo],
    subscribe_list: list[str] | None,
) -> list[dict[str, object]]:
    """将密函数据和本地类型图标转换为 HTML 模板 payload。"""

    entries: list[dict[str, object]] = []
    for mh in mh_result:
        if not mh.mh_type:
            logger.warning("mh_type is None: %s", mh.model_json_schema())
            continue
        type_name = get_mh_type_name(mh.mh_type)
        icon_path = TEXT_PATH / f"mh_{mh.mh_type}.png"
        entries.append(
            {
                "icon": image_data_uri(icon_path) if icon_path.exists() else None,
                "instances": [
                    {
                        "name": instance.name,
                        "subscribed": _is_subscribed(instance.name, type_name, subscribe_list),
                    }
                    for instance in mh.instances
                ],
                "type_name": type_name,
            }
        )
    return entries


async def draw_mh_simple(
    mh_result: list[DNARoleForToolInstanceInfo],
    remaining_seconds: int,
    subscribe_list: list[str] | None = None,
) -> bytes:
    """渲染固定高度的简洁密函图，保留旧动态列宽公式。"""

    card_width, gutter = 320, 20
    entries = _mh_payload(mh_result, subscribe_list)
    width = (card_width + gutter) * len(mh_result) + gutter
    return await _RENDERER.render(
        "cards/mh_simple.html.j2",
        {
            "entries": entries,
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "refresh_text": _simple_refresh_text(remaining_seconds),
            "width": width,
        },
        RenderSpec(width=width, height=646, full_page=True),
    )


async def draw_mh_card(
    mh_result: list[DNARoleForToolInstanceInfo],
    remaining_seconds: int,
    subscribe_list: list[str] | None = None,
    bg_name: str | None = None,
) -> bytes:
    """渲染旧 1700×900 密函卡片，随机背景仍由业务层选择。"""

    return await _RENDERER.render(
        "cards/mh_card.html.j2",
        {
            "background": image_data_uri(TEXT_PATH / (bg_name or random.choice(bg_list))),
            "bar": image_data_uri(TEXT_PATH / "bar.png"),
            "cards": _mh_payload(mh_result, subscribe_list),
            "card_background": image_data_uri(TEXT_PATH / "card.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer": image_data_uri(TEXT_PATH / "../.." / "utils" / "texture2d" / "footer.png"),
            "height": 900,
            "refresh_text": f"{format_seconds(remaining_seconds)}后刷新",
            "refresh_background": image_data_uri(TEXT_PATH / "refresh_time.png"),
            "title": image_data_uri(TEXT_PATH / "title.png"),
            "width": 1700,
        },
        # 网络 T2I 的 clip 高度被默认 viewport 截为 720px，固定根节点配合
        # full_page 才能得到旧版 1700x900 完整卡片。
        RenderSpec(width=1700, height=900, full_page=True, image_format="jpeg"),
    )


def format_seconds(seconds: int) -> str:
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}分钟{seconds}秒"


def _simple_refresh_text(seconds: int) -> str:
    """恢复旧简图 footer 的轮换时段和倒计时文本。"""

    now = get_datetime()
    return f"{now.hour}:00 - {(now.hour + 1) % 24}:00   {format_seconds(seconds)}后刷新"
