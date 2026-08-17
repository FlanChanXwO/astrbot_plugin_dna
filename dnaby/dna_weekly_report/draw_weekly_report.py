import asyncio
import math
from pathlib import Path

from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    build_profile_header,
    font_data_uri,
    image_data_uri,
    pil_image_data_uri,
)
from ..utils import dna_api
from ..utils.api.model import (
    DNAItemWeeklyReportRes,
    DNARoleForToolRes,
    RoleShowForTool,
)
from ..utils.database.models import DNABind
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image import download_pic_from_url
from ..utils.msgs.notify import (
    dna_not_found,
    dna_peek_blocked,
    dna_token_invalid,
    dna_uid_invalid,
)
from ..utils.resource.RESOURCE_PATH import WEEKLY_ITEM_PATH
from ..utils.session import EventContext, Sender
from ..utils.utils import get_using_id, is_peek_blocked, is_uid_hidden

_RENDERER = HtmlRenderer()
BACKGROUND_PATH = Path(__file__).parents[1] / "utils" / "texture2d" / "bg1.jpg"
QUALITY_PATH = Path(__file__).parent / "texture2d" / "quality"


def _fmt_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


async def _item_payload(item) -> dict[str, object]:
    name = f"item_{item.itemId}.png"
    path = WEEKLY_ITEM_PATH / name
    if path.exists():
        icon = image_data_uri(path)
    else:
        icon = pil_image_data_uri(
            await download_pic_from_url(WEEKLY_ITEM_PATH, item.icon, size=(105, 105), name=name)
        )
    quality = item.quality if 0 <= item.quality <= 5 else 0
    quality_path = QUALITY_PATH / f"q{quality}.png"
    return {
        "icon": icon,
        "name": item.itemName,
        "quality": image_data_uri(quality_path),
        "total": item.totalNum,
    }


async def _draw_weekly_report_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    report: DNAItemWeeklyReportRes,
    week_type: int = 1,
    uid_hidden: bool = False,
) -> bytes:
    other_info = [
        (item.paramKey, item.paramValue)
        for item in role_show.params
        if item.paramKey in ("总活跃天数", "游戏时长", "获得角色数")
    ]
    header = await build_profile_header(
        ctx,
        role_show.roleId,
        role_show.roleName,
        user_level=role_show.level,
        stats=other_info,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    category_items = await asyncio.gather(
        *(asyncio.gather(*(_item_payload(item) for item in category.items)) for category in report.categories)
    )
    categories = [
        {"items": list(items), "name": category.categoryName}
        for category, items in zip(report.categories, category_items, strict=True)
    ]
    height = 400 + sum(
        70 + max(1, math.ceil(len(category["items"]) / 5)) * 230 + 20
        for category in categories
    ) + 100
    return await _RENDERER.render(
        "cards/weekly_report.html.j2",
        {
            "background": image_data_uri(BACKGROUND_PATH),
            "categories": categories,
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"),
            "header": header,
            "header_background": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "avatar_title_bg.png"),
            "period": f"{_fmt_date(report.startDate)}  ~  {_fmt_date(report.endDate)}",
            "week_label": "本周周报" if week_type == 1 else "上周周报",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )


async def draw_weekly_report_img(sender: Sender, ctx: EventContext, week_type: int = 1):
    user_id = await get_using_id(ctx)
    if is_peek_blocked(ctx, user_id):
        return await dna_peek_blocked(sender, ctx)
    uid = await DNABind.get_uid_by_game(user_id, ctx.bot_id)
    if not uid:
        return await dna_uid_invalid(sender, ctx)
    dna_user = await dna_api.get_dna_user(uid, user_id, ctx.bot_id)
    if not dna_user:
        return await dna_token_invalid(sender, ctx)

    report_resp = await dna_api.get_item_weekly_report(dna_user, week_type)
    if not report_resp.is_success:
        return await dna_not_found(sender, ctx, "周报数据")
    report = DNAItemWeeklyReportRes.model_validate(report_resp.data)
    role_resp = await dna_api.get_default_role_for_tool(dna_user)
    if not role_resp.is_success:
        return await dna_not_found(sender, ctx, "角色列表信息")
    role_show = DNARoleForToolRes.model_validate(role_resp.data).roleInfo.roleShow
    uid_hidden = await is_uid_hidden(user_id, ctx.bot_id, ctx.group_id)

    card = await _draw_weekly_report_card(ctx, role_show, report, week_type=week_type, uid_hidden=uid_hidden)
    await sender.send(card)


draw_weekly_report_card = _draw_weekly_report_card

