import asyncio
import math
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

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


def weekly_item_display_name(name: str) -> str:
    return name if len(name) <= 8 else f"{name[:7]}…"



async def _item_payload(item, item_assets: dict[int, Image.Image | Path] | None = None) -> dict[str, object]:
    if item_assets and item.itemId in item_assets:
        asset = item_assets[item.itemId]
        if isinstance(asset, Path):
            icon = image_data_uri(asset)
        elif isinstance(asset, Image.Image):
            icon = pil_image_data_uri(asset)
        else:
            icon = str(asset)
    else:
        name = f"item_{item.itemId}.png"
        path = WEEKLY_ITEM_PATH / name
        if path.exists():
            icon = image_data_uri(path)
        else:
            try:
                img = await download_pic_from_url(WEEKLY_ITEM_PATH, item.icon, size=(105, 105), name=name)
                icon = pil_image_data_uri(img)
            except (OSError, httpx.HTTPError):
                fallback_img = Image.new("RGB", (105, 105), "#333333")
                icon = pil_image_data_uri(fallback_img)
    quality = item.quality if 0 <= item.quality <= 5 else 0
    quality_path = QUALITY_PATH / f"q{quality}.png"
    quality_uri = image_data_uri(quality_path) if quality_path.exists() else ""
    return {
        "icon": icon,
        "name": item.itemName,
        "quality": quality_uri,
        "total": item.totalNum,
    }


async def _draw_weekly_report_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    report: DNAItemWeeklyReportRes,
    week_type: int = 1,
    uid_hidden: bool = False,
    item_assets: dict[int, Image.Image | Path] | None = None,
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
        *(asyncio.gather(*(_item_payload(item, item_assets) for item in category.items)) for category in report.categories)
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


async def draw_weekly_report_card(*args, **kwargs) -> Image.Image | bytes:
    if len(args) >= 2 and isinstance(args[0], EventContext):
        ctx = args[0]
        role_show = args[1]
        report = args[2] if len(args) > 2 else kwargs.get("report")
        if report is None:
            raise ValueError("缺少 report 参数")
        week_type = int(kwargs.get("week_type", 1))
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        item_assets = kwargs.get("item_assets")
        return await _draw_weekly_report_card(
            ctx, role_show, report, week_type=week_type, uid_hidden=uid_hidden, item_assets=item_assets
        )
    elif len(args) >= 2:
        report = args[0]
        role_show = args[1]
        ctx = kwargs.get("ctx") or EventContext(user_id=kwargs.get("avatar_user_id", "0"))
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        item_assets = kwargs.get("item_assets")
        week_type = getattr(report, "weekType", 1)
        raw_bytes = await _draw_weekly_report_card(
            ctx, role_show, report, week_type=week_type, uid_hidden=uid_hidden, item_assets=item_assets
        )
        return Image.open(BytesIO(raw_bytes)).convert("RGBA")
    else:
        return await _draw_weekly_report_card(*args, **kwargs)




