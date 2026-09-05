"""百科与探索的 HTML/T2I 与确定性渲染器。"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from PIL import Image
from pydantic import BaseModel

from ...entry.event import EventActor
from ...modules.encyclopedia.contracts import (
    CalendarSnapshot,
    PlayerShortNote,
    WeeklyReport,
    WeeklyReportCategory,
    WeeklyReportItem,
)
from ...modules.player.contracts import RoleHeader, RoleOverview
from ...utils import dna_api
from ...utils.api.model import (
    DNAItemWeeklyReportRes,
    DNARoleForToolRes,
    DNARoleShortNoteRes,
    RoleShowForTool,
)
from ...utils.database.models import DNABind
from ...utils.image import download_pic_from_url
from ...utils.image_utils import crop_center_img, tint_image
from ...utils.msgs.notify import (
    dna_not_found,
    dna_peek_blocked,
    dna_token_invalid,
    dna_uid_invalid,
)
from ...utils.resource.RESOURCE_PATH import CALENDAR_PATH, WEEKLY_ITEM_PATH
from ...utils.session import EventContext, Sender
from ...utils.utils import get_using_id, is_peek_blocked, is_uid_hidden
from ..resources.encyclopedia import EncyclopediaResourceStore
from .artifact import RenderedArtifact
from .artifact_store import write_rendered_artifact
from .assets import font_data_uri, image_data_uri, pil_image_data_uri
from .payloads import build_profile_header
from .renderer import HtmlRenderer
from .spec import RenderSpec

_RENDERER = HtmlRenderer()
RESOURCES_DIR = Path(__file__).parents[2] / "resources"
COMMON_PATH = RESOURCES_DIR / "textures" / "common"
STAMINA_TEXT_PATH = RESOURCES_DIR / "textures" / "stamina"
WEEKLY_TEXT_PATH = RESOURCES_DIR / "textures" / "weekly_report"
CALENDAR_TEXT_PATH = RESOURCES_DIR / "textures" / "calendar"
TEXT_PATH = CALENDAR_TEXT_PATH
FONT_ORIGIN_PATH = RESOURCES_DIR / "fonts" / "dna_fonts.ttf"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _as_role_header(
    role: RoleHeader | RoleOverview | None,
    *,
    uid: str | None,
) -> RoleHeader:
    """将兼容输入收窄为便签/周报/签到所需的角色头部。"""

    if isinstance(role, RoleHeader):
        return role
    if isinstance(role, RoleOverview):
        return RoleHeader(
            role_id=role.role_id,
            role_name=role.role_name,
            level=role.level,
            params=list(role.params),
        )
    return RoleHeader(role_id=uid or "0", role_name="DNAUID", level=0)


# ---------------------------------------------------------------------------
# 1. 体力 / 日常便签 (Stamina)
# ---------------------------------------------------------------------------


def _get_stamina_bg_list() -> Path:
    bg_path = STAMINA_TEXT_PATH / "bg"
    if bg_path.is_dir():
        bg_list = [path for path in bg_path.iterdir() if path.suffix.lower() in (".jpg", ".png", ".webp")]
        if bg_list:
            return random.choice(bg_list)
    return COMMON_PATH / "bg.jpg"


def _progress_ratio(current: int, total: int) -> float:
    return min(current / total, 1) if total else 0


def _format_stamina_seconds(seconds: float) -> str:
    hours = int(seconds // 3600)
    minute = int((seconds % 3600) // 60)
    second = int(seconds % 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}"


async def _draw_stamina_card_view(
    ctx: EventContext,
    role: RoleHeader,
    short_note: PlayerShortNote,
    uid_hidden: bool = False,
    bg_path: Path | None = None,
) -> bytes:
    """直接从便签/角色头部 DTO 构造模板输入。"""

    other_info = [
        (item.param_key, item.param_value)
        for item in role.params
        if item.param_key in ("总活跃天数", "游戏时长", "获得角色数")
    ]
    header = await build_profile_header(
        ctx,
        role.role_id,
        role.role_name,
        user_level=role.level,
        stats=other_info,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    raw_notes = [
        ("备忘手记", short_note.current_task_progress, short_note.max_daily_task_progress),
        ("迷津", short_note.rouge_like_reward_count, short_note.rouge_like_reward_total),
        ("梦魇残声", short_note.hard_boss_reward_count, short_note.hard_boss_reward_total),
        ("竞逐", short_note.dungeon_reward, short_note.dungeon_reward_total),
    ]
    notes = [
        {
            "current": current,
            "icon": pil_image_data_uri(
                tint_image(Image.open(STAMINA_TEXT_PATH / f"icon{index}.png"), (240, 230, 140)),
            ),
            "name": name,
            "ratio": _progress_ratio(current, total),
            "total": total,
        }
        for index, (name, current, total) in enumerate(raw_notes, start=1)
    ]

    drafts: list[dict[str, object]] = []
    now = int(time.time())
    for draft in short_note.drafts:
        if not draft.product_name or draft.end_at is None:
            continue
        end_at = int(draft.end_at.timestamp())
        is_done = draft.completed or now > end_at
        drafts.append(
            {
                "done": is_done,
                "name": draft.product_name,
                "state": "已完成" if is_done else _format_stamina_seconds(end_at - now),
            }
        )

    selected_bg = bg_path or _get_stamina_bg_list()
    return await _RENDERER.render(
        "cards/stamina.html.j2",
        {
            "background": image_data_uri(selected_bg),
            "drafts": drafts,
            "divider": image_data_uri(STAMINA_TEXT_PATH / "div.png"),
            "foreground": image_data_uri(STAMINA_TEXT_PATH / "fg.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "header": header,
            "header_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "bar_background": image_data_uri(STAMINA_TEXT_PATH / "bar_bg2.png"),
            "success": image_data_uri(STAMINA_TEXT_PATH / "success.png"),
            "running": image_data_uri(STAMINA_TEXT_PATH / "running.png"),
            "draft_background": image_data_uri(STAMINA_TEXT_PATH / "draft_bg.png"),
            "height": 1100,
            "notes": notes,
            "width": 2000,
        },
        RenderSpec(width=2000, height=1100, full_page=True, output_format="jpeg"),
    )


async def _draw_stamina_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    short_note_info: DNARoleShortNoteRes,
    uid_hidden: bool = False,
    bg_path: Path | None = None,
) -> bytes:
    """组装 legacy 便签 payload；typed DTO 走最小 view 分支。"""

    if isinstance(role_show, RoleHeader) and isinstance(short_note_info, PlayerShortNote):
        return await _draw_stamina_card_view(
            ctx, role_show, short_note_info, uid_hidden=uid_hidden, bg_path=bg_path
        )

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

    raw_notes = [
        ("备忘手记", short_note_info.currentTaskProgress, short_note_info.maxDailyTaskProgress),
        ("迷津", short_note_info.rougeLikeRewardCount, short_note_info.rougeLikeRewardTotal),
        ("梦魇残声", short_note_info.hardBossRewardCount, short_note_info.hardBossRewardTotal),
        ("竞逐", short_note_info.dungeonReward, short_note_info.dungeonRewardTotal),
    ]
    notes = [
        {
            "current": current,
            "icon": pil_image_data_uri(
                tint_image(Image.open(STAMINA_TEXT_PATH / f"icon{index}.png"), (240, 230, 140)),
            ),
            "name": name,
            "ratio": _progress_ratio(current, total),
            "total": total,
        }
        for index, (name, current, total) in enumerate(raw_notes, start=1)
    ]

    drafts: list[dict[str, object]] = []
    draft_info = short_note_info.draftInfo
    if draft_info and draft_info.draftDoingNum > 0 and draft_info.draftDoingInfo:
        now = int(time.time())
        for draft in draft_info.draftDoingInfo:
            if not draft.productName or not draft.endTime:
                continue
            is_done = now > int(draft.endTime)
            drafts.append(
                {
                    "done": is_done,
                    "name": draft.productName,
                    "state": "已完成" if is_done else _format_stamina_seconds(int(draft.endTime) - now),
                }
            )

    selected_bg = bg_path or _get_stamina_bg_list()
    return await _RENDERER.render(
        "cards/stamina.html.j2",
        {
            "background": image_data_uri(selected_bg),
            "drafts": drafts,
            "divider": image_data_uri(STAMINA_TEXT_PATH / "div.png"),
            "foreground": image_data_uri(STAMINA_TEXT_PATH / "fg.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "header": header,
            "header_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "bar_background": image_data_uri(STAMINA_TEXT_PATH / "bar_bg2.png"),
            "success": image_data_uri(STAMINA_TEXT_PATH / "success.png"),
            "running": image_data_uri(STAMINA_TEXT_PATH / "running.png"),
            "draft_background": image_data_uri(STAMINA_TEXT_PATH / "draft_bg.png"),
            "height": 1100,
            "notes": notes,
            "width": 2000,
        },
        RenderSpec(width=2000, height=1100, full_page=True, output_format="jpeg"),
    )


async def draw_stamina_card(*args, **kwargs) -> Image.Image | bytes:
    if len(args) >= 2 and isinstance(args[1], RoleShowForTool):
        ctx = args[0]
        role_show = args[1]
        short_note = args[2] if len(args) > 2 else kwargs.get("short_note_info")
        if short_note is None:
            raise ValueError("缺少 short_note_info 参数")
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        return await _draw_stamina_card(ctx, role_show, short_note, uid_hidden=uid_hidden)
    elif len(args) >= 2:
        short_note = args[0]
        role_info = args[1]
        role_show = role_info.roleInfo.roleShow if hasattr(role_info, "roleInfo") else role_info
        ctx = kwargs.get("ctx") or EventContext(user_id=kwargs.get("avatar_user_id", "0"))
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        raw_bytes = await _draw_stamina_card(ctx, role_show, short_note, uid_hidden=uid_hidden)
        return Image.open(BytesIO(raw_bytes)).convert("RGBA")
    else:
        return await _draw_stamina_card(*args, **kwargs)


async def draw_stamina_img(sender: Sender, ctx: EventContext):
    user_id = await get_using_id(ctx)
    if is_peek_blocked(ctx, user_id):
        await dna_peek_blocked(sender, ctx)
        return
    uid = await DNABind.get_uid_by_game(user_id, ctx.bot_id)
    if not uid:
        await dna_uid_invalid(sender, ctx)
        return

    dna_user = await dna_api.get_dna_user(uid, user_id, ctx.bot_id)
    if not dna_user:
        await dna_token_invalid(sender, ctx)
        return

    short_note_info = await dna_api.get_short_note_info(dna_user)
    if not short_note_info.is_success:
        await dna_not_found(sender, ctx, "日常便签数据")
        return
    short_note_res = DNARoleShortNoteRes.model_validate(short_note_info.data)

    role_for_tool_info = await dna_api.get_default_role_for_tool(dna_user)
    if not role_for_tool_info.is_success:
        await dna_not_found(sender, ctx, "角色列表信息")
        return
    role_show = DNARoleForToolRes.model_validate(role_for_tool_info.data).roleInfo.roleShow
    uid_hidden = await is_uid_hidden(user_id, ctx.bot_id, ctx.group_id)

    card = await _draw_stamina_card(ctx, role_show, short_note_res, uid_hidden=uid_hidden)
    await sender.send(card)


# ---------------------------------------------------------------------------
# 2. 探险周报 (Weekly Report)
# ---------------------------------------------------------------------------


def _fmt_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def weekly_item_display_name(name: str) -> str:
    return name if len(name) <= 8 else f"{name[:7]}…"


async def _weekly_item_payload(item, item_assets: dict[int, Image.Image | Path] | None = None) -> dict[str, object]:
    item_id = getattr(item, "item_id", getattr(item, "itemId", 0))
    item_name = getattr(item, "item_name", getattr(item, "itemName", ""))
    item_icon = getattr(item, "icon", "") or ""
    item_quality = getattr(item, "quality", 0)
    item_total = getattr(item, "total_num", getattr(item, "totalNum", "0"))
    quality_dir = WEEKLY_TEXT_PATH / "quality"
    if item_assets and item_id in item_assets:
        asset = item_assets[item_id]
        if isinstance(asset, Path):
            icon = image_data_uri(asset)
        elif isinstance(asset, Image.Image):
            icon = pil_image_data_uri(asset)
        else:
            icon = str(asset)
    else:
        name = f"item_{item_id}.png"
        path = WEEKLY_ITEM_PATH / name
        if path.exists():
            icon = image_data_uri(path)
        else:
            try:
                img = await download_pic_from_url(WEEKLY_ITEM_PATH, item_icon, size=(105, 105), name=name)
                icon = pil_image_data_uri(img)
            except (OSError, httpx.HTTPError):
                fallback_img = Image.new("RGB", (105, 105), "#333333")
                icon = pil_image_data_uri(fallback_img)
    quality = item_quality if 0 <= item_quality <= 5 else 0
    quality_path = quality_dir / f"q{quality}.png"
    quality_uri = image_data_uri(quality_path) if quality_path.exists() else ""
    return {
        "icon": icon,
        "name": item_name,
        "quality": quality_uri,
        "total": str(item_total),
    }


async def _draw_weekly_report_card_view(
    ctx: EventContext,
    role: RoleHeader,
    report: WeeklyReport,
    week_type: int = 1,
    uid_hidden: bool = False,
    item_assets: dict[int, Image.Image | Path] | None = None,
) -> bytes:
    """直接从周报领域 DTO 构造模板输入。"""

    other_info = [
        (item.param_key, item.param_value)
        for item in role.params
        if item.param_key in ("总活跃天数", "游戏时长", "获得角色数")
    ]
    header = await build_profile_header(
        ctx,
        role.role_id,
        role.role_name,
        user_level=role.level,
        stats=other_info,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    category_items = await asyncio.gather(
        *(
            asyncio.gather(
                *(_weekly_item_payload(item, item_assets) for item in category.items)
            )
            for category in report.categories
        )
    )
    categories = [
        {"items": list(items), "name": category.category_name}
        for category, items in zip(report.categories, category_items, strict=True)
    ]
    height = 400 + sum(
        70 + max(1, math.ceil(len(category["items"]) / 5)) * 230 + 20
        for category in categories
    ) + 100
    return await _RENDERER.render(
        "cards/weekly_report.html.j2",
        {
            "background": image_data_uri(COMMON_PATH / "bg1.jpg"),
            "categories": categories,
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "header": header,
            "header_background": image_data_uri(
                COMMON_PATH / "avatar_title_bg.png"
            ),
            "period": f"{_fmt_date(report.start_date)}  ~  {_fmt_date(report.end_date)}",
            "week_label": "本周周报" if week_type == 1 else "上周周报",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, output_format="jpeg"),
    )


async def _draw_weekly_report_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    report: DNAItemWeeklyReportRes,
    week_type: int = 1,
    uid_hidden: bool = False,
    item_assets: dict[int, Image.Image | Path] | None = None,
) -> bytes:
    if isinstance(role_show, RoleHeader) and isinstance(report, WeeklyReport):
        return await _draw_weekly_report_card_view(
            ctx,
            role_show,
            report,
            week_type=week_type,
            uid_hidden=uid_hidden,
            item_assets=item_assets,
        )

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
        *(asyncio.gather(*(_weekly_item_payload(item, item_assets) for item in category.items)) for category in report.categories)
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
            "background": image_data_uri(COMMON_PATH / "bg1.jpg"),
            "categories": categories,
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "header": header,
            "header_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "period": f"{_fmt_date(report.startDate)}  ~  {_fmt_date(report.endDate)}",
            "week_label": "本周周报" if week_type == 1 else "上周周报",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, output_format="jpeg"),
    )


async def draw_weekly_report_card(*args, **kwargs) -> Image.Image | bytes:
    if len(args) >= 2 and isinstance(args[1], RoleShowForTool):
        ctx = args[0]
        role_show = args[1]
        report = args[2] if len(args) > 2 else kwargs.get("report")
        if report is None:
            raise ValueError("缺少 report 参数")
        week_type = int(kwargs.get("week_type", 1))
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        item_assets = kwargs.get("item_assets")
        return await _draw_weekly_report_card(
            ctx,
            role_show,
            report,
            week_type=week_type,
            uid_hidden=uid_hidden,
            item_assets=item_assets,
        )
    elif len(args) >= 2:
        report = args[0]
        role_info = args[1]
        role_show = role_info.roleInfo.roleShow if hasattr(role_info, "roleInfo") else role_info
        ctx = kwargs.get("ctx") or EventContext(user_id=kwargs.get("avatar_user_id", "0"))
        week_type = int(kwargs.get("week_type", 1))
        uid_hidden = bool(kwargs.get("uid_hidden", False))
        item_assets = kwargs.get("item_assets")
        raw_bytes = await _draw_weekly_report_card(
            ctx,
            role_show,
            report,
            week_type=week_type,
            uid_hidden=uid_hidden,
            item_assets=item_assets,
        )
        return Image.open(BytesIO(raw_bytes)).convert("RGBA")
    else:
        return await _draw_weekly_report_card(*args, **kwargs)


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

    weekly_report_info = await dna_api.get_item_weekly_report(dna_user, week_type)
    if not weekly_report_info.is_success:
        return await dna_not_found(sender, ctx, "周报数据")
    report = DNAItemWeeklyReportRes.model_validate(weekly_report_info.data)

    role_for_tool_info = await dna_api.get_default_role_for_tool(dna_user)
    if not role_for_tool_info.is_success:
        return await dna_not_found(sender, ctx, "角色列表信息")
    role_show = DNARoleForToolRes.model_validate(role_for_tool_info.data).roleInfo.roleShow
    uid_hidden = await is_uid_hidden(user_id, ctx.bot_id, ctx.group_id)

    card = await _draw_weekly_report_card(ctx, role_show, report, week_type=week_type, uid_hidden=uid_hidden)
    await sender.send(card)


# ---------------------------------------------------------------------------
# 3. 活动日历 (Calendar)
# ---------------------------------------------------------------------------


class TimeType(str, Enum):
    MOLING = "moling"
    MIHAN = "mihan"
    ZHOUBEN = "zhouben"


START_TIME = {
    TimeType.MOLING: {
        "start_time": datetime(2026, 1, 3, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 86400 * 3,
    },
    TimeType.MIHAN: {
        "start_time": datetime(2026, 1, 3, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 3600,
    },
    TimeType.ZHOUBEN: {
        "start_time": datetime(2025, 12, 29, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 86400 * 7,
    },
}


def get_time(now: datetime, time_type: TimeType):
    if now.tzinfo is None:
        now = now.replace(tzinfo=SHANGHAI_TZ)
    else:
        now = now.astimezone(SHANGHAI_TZ)
    start_time = START_TIME[time_type]["start_time"]
    date_range = START_TIME[time_type]["date_range"]
    date_range_td = timedelta(seconds=date_range)
    elapsed_time = (now - start_time).total_seconds()
    period_index = int(elapsed_time // date_range)
    period_start = start_time + period_index * date_range_td
    period_end = period_start + date_range_td
    return {
        "start_time": period_start,
        "end_time": period_end,
        "start_date_str": period_start.strftime("%Y-%m-%d %H:%M"),
        "end_date_str": period_end.strftime("%Y-%m-%d %H:%M"),
    }


class CalendarContent(BaseModel):
    title: str
    pic: str
    start_time: str | int
    end_time: str | int


def _calendar_background(height: int) -> Image.Image:
    """按旧 PIL 的中心裁剪规则生成最终画布背景。"""

    with Image.open(CALENDAR_TEXT_PATH / "bg.jpg") as opened:
        return crop_center_img(opened.convert("RGBA"), 1200, height)


async def _load_banner(height: int) -> str:
    """按旧 PIL 合成顺序预合成 banner，避免 T2I 对透明 JPEG 的底色差异。"""

    banner_bg = Image.open(CALENDAR_TEXT_PATH / "banner_bg.webp").convert("RGBA").resize((1200, 675))
    banner_mask = Image.open(CALENDAR_TEXT_PATH / "banner_mask.png").getchannel("A")
    banner_bg = crop_center_img(banner_bg, banner_mask.width, banner_mask.height)
    background = _calendar_background(height).crop((0, 150, 1200, 750))
    banner = Image.alpha_composite(background, Image.merge("RGBA", (*banner_bg.split()[:3], banner_mask)))
    frame = Image.open(CALENDAR_TEXT_PATH / "banner_frame.png").convert("RGBA")
    banner.alpha_composite(frame)
    return pil_image_data_uri(banner)


def _event_dates(cont: CalendarContent) -> list[str]:
    date_range: list[str] = []
    if isinstance(cont.start_time, str) and cont.start_time:
        date_range.append(cont.start_time)
    if isinstance(cont.end_time, str) and cont.end_time:
        date_range.append(cont.end_time)
    if isinstance(cont.start_time, int) and cont.start_time > 0:
        date_range.append(datetime.fromtimestamp(cont.start_time, tz=SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M"))
    if isinstance(cont.end_time, int) and cont.end_time > 0:
        date_range.append(datetime.fromtimestamp(cont.end_time, tz=SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M"))
    return date_range


def get_left_time_str(remaining_time: timedelta) -> str:
    remaining_days = remaining_time.days
    remaining_hours, remaining_minutes = divmod(remaining_time.seconds, 3600)
    remaining_minutes, _ = divmod(remaining_minutes, 60)
    return f"还剩{remaining_days}天{remaining_hours}小时{remaining_minutes}分钟"


def get_date_range(dateRange: list[str], now: datetime):
    start_time = datetime.strptime(dateRange[0], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    end_time = datetime.strptime(dateRange[1], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    now = now.replace(tzinfo=SHANGHAI_TZ) if now.tzinfo is None else now.astimezone(SHANGHAI_TZ)
    if start_time <= now <= end_time:
        remaining_time = end_time - now
        return "进行中", get_left_time_str(remaining_time), "red" if remaining_time.days < 1 else "white"
    if now > end_time:
        return "已结束", "", "white"
    return "未开始", "", "white"


def _event_payload(cont: CalendarContent, now: datetime) -> dict[str, object]:
    date_range = _event_dates(cont)
    payload: dict[str, object] = {
        "date_range": " ~ ".join(date_range),
        "icon": None,
        "left": "",
        "left_color": "white",
        "progress": 0,
        "progress_color": "gold",
        "status": "",
        "title": cont.title,
    }
    if len(date_range) < 2:
        return payload

    start_time = datetime.strptime(date_range[0], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    end_time = datetime.strptime(date_range[1], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    status, left, color = get_date_range(date_range, now)
    if status == "已结束":
        progress = 1.0
    else:
        total_duration = (end_time - start_time).total_seconds()
        progress = (now - start_time).total_seconds() / total_duration if total_duration > 0 else 0
    payload.update(
        {
            "date_range": f"{start_time:%m.%d %H:%M} ~ {end_time:%m.%d %H:%M}",
            "left": left,
            "left_color": color,
            "progress": max(0.0, min(progress, 1.0)),
            "progress_color": "white" if status == "已结束" else ("gold" if color == "white" else color),
            "status": status,
        }
    )
    return payload


async def _event_image(cont: CalendarContent) -> str | None:
    if not cont.pic:
        return None
    if "http" in cont.pic:
        image = await download_pic_from_url(CALENDAR_PATH, cont.pic, size=(100, 100))
        return pil_image_data_uri(image)
    pic_path = CALENDAR_TEXT_PATH / cont.pic
    return image_data_uri(pic_path) if pic_path.exists() else None


async def _draw_calendar_card_bytes(
    content: list[CalendarContent],
    calendar_assets: Mapping[str, Image.Image | Path] | None = None,
    now: datetime | None = None,
) -> bytes:
    if now is None:
        now = datetime.now(SHANGHAI_TZ)
    events = []
    for item in content:
        event = _event_payload(item, now)
        if calendar_assets and item.pic in calendar_assets:
            asset = calendar_assets[item.pic]
            if isinstance(asset, Path):
                event["icon"] = image_data_uri(asset)
            elif isinstance(asset, Image.Image):
                event["icon"] = pil_image_data_uri(asset)
            else:
                event["icon"] = str(asset)
        else:
            event["icon"] = await _event_image(item)
        events.append(event)

    height = 880 + 170 * ((len(events) + 1) // 2)
    background = _calendar_background(height)

    raw_bytes = await _RENDERER.render(
        "cards/calendar.html.j2",
        {
            "background": pil_image_data_uri(background.convert("RGB"), image_format="JPEG"),
            "banner": await _load_banner(height),
            "events": events,
            "event_background": image_data_uri(CALENDAR_TEXT_PATH / "event_bg.png"),
            "bar": image_data_uri(CALENDAR_TEXT_PATH / "bar.png"),
            "time_icon": image_data_uri(CALENDAR_TEXT_PATH / "time_icon.png"),
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )
    return raw_bytes


async def draw_calendar_card(
    content: list[CalendarContent],
    calendar_assets: Mapping[str, Image.Image | Path] | None = None,
    now: datetime | None = None,
) -> Image.Image:
    """兼容旧调用者返回 Pillow 图像；运行期 renderer 使用 raw bytes 边界。"""

    raw_bytes = await _draw_calendar_card_bytes(content, calendar_assets, now)
    return Image.open(BytesIO(raw_bytes)).convert("RGBA")


async def draw_calendar_img(ctx: EventContext):
    activity_res = await dna_api.get_activity_info()
    activity_list = activity_res.data.get("activities", []) if activity_res.is_success and isinstance(activity_res.data, dict) else []

    wiki_list = []
    wiki_home = await dna_api.get_calendar_info()
    if wiki_home:
        jumu = next(filter(lambda x: x["sectionType"] == 3 and x.get("activityUps") is not None, wiki_home), None)
        old_activity_list = next(filter(lambda x: x["sectionType"] == 3 and x.get("activities") is not None, wiki_home), None)
        if jumu:
            wiki_list.append(jumu)
        if old_activity_list:
            wiki_list.append(old_activity_list)

    if not activity_list and not wiki_list:
        return "获取日历失败"

    now = datetime.now(tz=SHANGHAI_TZ)
    content = [
        CalendarContent(title="魔灵", pic="moling.png", start_time=get_time(now, TimeType.MOLING)["start_date_str"], end_time=get_time(now, TimeType.MOLING)["end_date_str"]),
        CalendarContent(title="周本", pic="zhouben.png", start_time=get_time(now, TimeType.ZHOUBEN)["start_date_str"], end_time=get_time(now, TimeType.ZHOUBEN)["end_date_str"]),
    ]
    if wiki_list:
        for item in wiki_list:
            for activity_up in item.get("activityUps", []):
                start_time, end_time = activity_up.get("createTime"), activity_up.get("endTime")
                content.extend(
                    CalendarContent(
                        title=activity_up.get("name") or entry["name"],
                        pic=entry["pic"],
                        start_time=int(start_time / 1000) if start_time else "",
                        end_time=int(end_time / 1000) if end_time else "",
                    )
                    for entry in activity_up["contents"]
                )
            for activity in item.get("activities", []):
                content.append(
                    CalendarContent(
                        title=activity["name"],
                        pic=activity["pic"],
                        start_time=int(activity["createTime"] / 1000) if activity["createTime"] else "",
                        end_time=int(activity["endTime"] / 1000) if activity["endTime"] else "",
                    )
                )
    for activity in activity_list:
        if activity.get("cycleDay", -1) != -1 or "委托密函轮换" in activity["name"]:
            continue
        start_time, end_time = activity.get("startTime"), activity.get("endTime")
        content.append(
            CalendarContent(
                title=activity["name"],
                pic=activity.get("icon", ""),
                start_time=int(start_time / 1000) if start_time else "",
                end_time=int(end_time / 1000) if end_time else "",
            )
        )

    events = []
    for item in content:
        event = _event_payload(item, now)
        event["icon"] = await _event_image(item)
        events.append(event)

    height = 880 + 170 * ((len(events) + 1) // 2)
    background = _calendar_background(height)

    return await _RENDERER.render(
        "cards/calendar.html.j2",
        {
            "background": pil_image_data_uri(background.convert("RGB"), image_format="JPEG"),
            "banner": await _load_banner(height),
            "events": events,
            "event_background": image_data_uri(CALENDAR_TEXT_PATH / "event_bg.png"),
            "bar": image_data_uri(CALENDAR_TEXT_PATH / "bar.png"),
            "time_icon": image_data_uri(CALENDAR_TEXT_PATH / "time_icon.png"),
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )


# ---------------------------------------------------------------------------
# 4. EncyclopediaRenderer Class
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RenderedEncyclopediaImage:
    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]
    sidecar: Path | None = None
    manifest: Path | None = None
    media_type: str = "image/jpeg"


def _value(val: Any) -> str:
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            val = val.astimezone(SHANGHAI_TZ)
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)


def _legacy_role_payload(role: RoleOverview) -> dict[str, Any]:
    role_payload = role.model_dump(by_alias=True)
    role_payload.pop("achievementTotal", None)
    role_payload["roleAchv"] = {"total": role.achievement_total}
    return {"roleInfo": {"roleShow": role_payload}}


class EncyclopediaRenderer:
    """生成百科/便签/周报/日历卡片的运行期 PNG。"""

    def __init__(self, output_dir: str | Path, resources: EncyclopediaResourceStore) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources

    def _font_resource(self) -> dict[str, str]:
        return {
            "kind": "font",
            "key": "dna_fonts",
            "status": self.resources.font_status,
            "source": "fonts/dna_fonts.ttf" if self.resources.font_path is not None else "",
        }

    def _write(
        self,
        image_bytes: bytes,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
        media_type: str = "image/jpeg",
    ) -> RenderedEncyclopediaImage:
        artifact = RenderedArtifact.from_bytes(
            image_bytes,
            media_type=media_type,  # type: ignore[arg-type]
            metadata={
                "dnaby.text": "\n".join(lines),
                "dnaby.layout": {
                    "width": None,
                    "height": None,
                    "sections": sections,
                },
                "dnaby.resources": resources,
            },
        )
        # 尺寸先由容器检查器读取，再补入 sidecar；图片 bytes 保持原样。
        metadata = dict(artifact.metadata)
        metadata["dnaby.layout"] = {
            "width": artifact.width,
            "height": artifact.height,
            "sections": sections,
        }
        artifact = RenderedArtifact.from_bytes(
            image_bytes,
            media_type=media_type,  # type: ignore[arg-type]
            metadata=metadata,
        )
        response = write_rendered_artifact(
            self.output_dir,
            artifact,
            prefix="encyclopedia-",
        )
        return RenderedEncyclopediaImage(
            path=Path(response.image),
            width=artifact.width,
            height=artifact.height,
            text_lines=tuple(lines),
            resources=tuple(resources),
            sections=tuple(sections),
            sidecar=Path(response.sidecar) if response.sidecar else None,
            manifest=Path(response.manifest) if response.manifest else None,
            media_type=artifact.media_type,
        )

    async def render_stamina(
        self,
        snapshot: Any,
        role: RoleHeader | RoleOverview | None = None,
        *,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
        uid: str | None = None,
        uid_hidden: bool = False,
    ) -> RenderedEncyclopediaImage:
        typed_snapshot = isinstance(snapshot, PlayerShortNote)
        if typed_snapshot:
            role = _as_role_header(
                role if role is not None else snapshot.role_overview,
                uid=uid,
            )
            role_show = role
            short_note = snapshot
        else:
            if role is None:
                role = getattr(snapshot, "role_overview", None)
            if role is None:
                role = RoleOverview(
                    role_id=uid or "0",
                    role_name="DNAUID",
                    level=0,
                    achievement_total=0,
                )
            role_payload = _legacy_role_payload(role)["roleInfo"]["roleShow"]
            role_show = DNARoleForToolRes.model_validate(
                {"roleInfo": {"roleShow": role_payload}},
            ).roleInfo.roleShow

            if hasattr(snapshot, "model_dump"):
                short_note = DNARoleShortNoteRes.model_validate(snapshot.model_dump(by_alias=True))
            else:
                drafts = getattr(snapshot, "drafts", ())
                doing_items = [
                    {
                        "name": d.product_name,
                        "productName": d.product_name,
                        "startTime": _value(d.start_at) if d.start_at else "0",
                        "endTime": str(int(d.end_at.timestamp())) if d.end_at else "0",
                        "draftCompleteNum": 0,
                        "draftDoingNum": 1,
                    }
                    for d in drafts
                    if not d.completed and d.product_name
                ]
                short_note_dict = {
                    "currentTaskProgress": getattr(snapshot, "current_task_progress", 0),
                    "maxDailyTaskProgress": getattr(snapshot, "max_daily_task_progress", 0),
                    "rougeLikeRewardCount": getattr(snapshot, "rouge_like_reward_count", getattr(snapshot, "rougelike_reward_count", 0)),
                    "rougeLikeRewardTotal": getattr(snapshot, "rouge_like_reward_total", getattr(snapshot, "rougelike_reward_total", 0)),
                    "hardBossRewardCount": getattr(snapshot, "hard_boss_reward_count", 0),
                    "hardBossRewardTotal": getattr(snapshot, "hard_boss_reward_total", 0),
                    "dungeonReward": getattr(snapshot, "dungeon_reward", 0),
                    "dungeonRewardTotal": getattr(snapshot, "dungeon_reward_total", 0),
                    "draftInfo": {
                        "draftDoingNum": getattr(snapshot, "draft_doing_num", len(doing_items)),
                        "draftMaxNum": getattr(snapshot, "draft_max_num", 5),
                        "draftDoingInfo": doing_items,
                    },
                }
                short_note = DNARoleShortNoteRes.model_validate(short_note_dict)

        if typed_snapshot:
            current_task_progress = snapshot.current_task_progress
            max_daily_task_progress = snapshot.max_daily_task_progress
            hard_boss_reward_count = snapshot.hard_boss_reward_count
            hard_boss_reward_total = snapshot.hard_boss_reward_total
            dungeon_reward = snapshot.dungeon_reward
            dungeon_reward_total = snapshot.dungeon_reward_total
        else:
            current_task_progress = getattr(snapshot, "current_task_progress", 0)
            max_daily_task_progress = getattr(snapshot, "max_daily_task_progress", 0)
            hard_boss_reward_count = getattr(snapshot, "hard_boss_reward_count", 0)
            hard_boss_reward_total = getattr(snapshot, "hard_boss_reward_total", 0)
            dungeon_reward = getattr(snapshot, "dungeon_reward", 0)
            dungeon_reward_total = getattr(snapshot, "dungeon_reward_total", 0)

        avatar_user_id = target_user_id or (actor.user_id if actor is not None else (uid or "0"))
        ctx = EventContext(
            user_id=avatar_user_id,
            bot_id="" if actor is None else actor.bot_id,
            group_id="" if actor is None or actor.group_id is None else actor.group_id,
            at=avatar_user_id,
            unified_msg_origin="" if actor is None or actor.unified_msg_origin is None else actor.unified_msg_origin,
        )
        image_bytes = await _draw_stamina_card(ctx, role_show, short_note, uid_hidden=uid_hidden)

        rougelike_count = getattr(snapshot, "rouge_like_reward_count", getattr(snapshot, "rougelike_reward_count", 0))
        rougelike_total = getattr(snapshot, "rouge_like_reward_total", getattr(snapshot, "rougelike_reward_total", 0))
        lines = [
            role.role_name,
            f"UID {'***' if uid_hidden else role.role_id}",
            f"备忘手记: {current_task_progress}/{max_daily_task_progress}",
            f"迷津: {rougelike_count}/{rougelike_total}",
            f"梦魇残声: {hard_boss_reward_count}/{hard_boss_reward_total}",
            f"竞逐: {dungeon_reward}/{dungeon_reward_total}",
        ]
        lines.extend(f"{item.param_key}: {item.param_value}" for item in role.params)
        drafts = getattr(snapshot, "drafts", None)
        if drafts is not None:
            for d in drafts:
                if d.completed:
                    lines.append(f"已完成: {d.product_name}")
                    lines.append(d.product_name)
                else:
                    lines.append(f"生产: {d.product_name}")
                    lines.append(d.product_name)
        elif getattr(snapshot, "draft_info", None) is not None:
            lines.extend(f"生产: {item.name}" for item in snapshot.draft_info.doing_items if item.name)
            lines.extend(f"已完成: {item.name}" for item in snapshot.draft_info.finish_items if item.name)

        resources = [
            self._font_resource(),
            {
                "kind": "texture_dir",
                "key": "stamina_textures",
                "status": "legacy",
                "source": "resources/textures/stamina",
            },
        ]
        sections = [
            {"name": "日常便签", "items": 4},
            {"name": "图纸生产", "items": len(getattr(snapshot, "drafts", ())) if drafts is not None else (0 if getattr(snapshot, "draft_info", None) is None else snapshot.draft_info.draft_doing_num)},
        ]
        return self._write(image_bytes, lines=lines, resources=resources, sections=sections)

    async def render_weekly_report(
        self,
        snapshot: Any,
        role: RoleHeader | RoleOverview | None = None,
        *,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
        uid: str | None = None,
        uid_hidden: bool = False,
    ) -> RenderedEncyclopediaImage:
        typed_snapshot = isinstance(snapshot, WeeklyReport)
        if typed_snapshot:
            role = _as_role_header(
                role if role is not None else snapshot.role_overview,
                uid=uid,
            )
            role_show = role
            report = snapshot
            report_week_type = snapshot.week_type
            report_start_date = snapshot.start_date
            report_end_date = snapshot.end_date
        else:
            if role is None:
                role = getattr(snapshot, "role_overview", None)
            if role is None:
                role = RoleOverview(
                    role_id=uid or "0",
                    role_name="DNAUID",
                    level=0,
                    achievement_total=0,
                )
            role_payload = _legacy_role_payload(role)["roleInfo"]["roleShow"]
            role_show = DNARoleForToolRes.model_validate(
                {"roleInfo": {"roleShow": role_payload}},
            ).roleInfo.roleShow

            if hasattr(snapshot, "model_dump"):
                report = DNAItemWeeklyReportRes.model_validate(snapshot.model_dump(by_alias=True))
                report_week_type = report.weekType
                report_start_date = report.startDate
                report_end_date = report.endDate
            else:
                report_dict = {
                    "weekType": snapshot.week_type,
                    "startDate": snapshot.start_date,
                    "endDate": snapshot.end_date,
                    "categories": [
                        {
                            "categoryName": cat.category_name,
                            "type": cat.category_type,
                            "isBase": cat.is_base,
                            "items": [
                                {
                                    "itemId": item.item_id,
                                    "itemName": item.item_name,
                                    "quality": item.quality,
                                    "totalNum": str(item.total_num),
                                    "icon": item.icon,
                                }
                                for item in cat.items
                            ],
                        }
                        for cat in snapshot.categories
                    ],
                }
                report = DNAItemWeeklyReportRes.model_validate(report_dict)
                report_week_type = snapshot.week_type
                report_start_date = snapshot.start_date
                report_end_date = snapshot.end_date

        avatar_user_id = target_user_id or (actor.user_id if actor is not None else (uid or "0"))
        ctx = EventContext(
            user_id=avatar_user_id,
            bot_id="" if actor is None else actor.bot_id,
            group_id="" if actor is None or actor.group_id is None else actor.group_id,
            at=avatar_user_id,
            unified_msg_origin="" if actor is None or actor.unified_msg_origin is None else actor.unified_msg_origin,
        )
        image_bytes = await _draw_weekly_report_card(
            ctx,
            role_show,
            report,
            week_type=report_week_type,
            uid_hidden=uid_hidden,
        )

        lines = [
            role.role_name,
            f"UID {'***' if uid_hidden else role.role_id}",
            f"周期: {_fmt_date(report_start_date)} ~ {_fmt_date(report_end_date)}",
        ]
        if report_week_type == 2:
            lines.append("上周周报")
        if typed_snapshot:
            categories = snapshot.categories
        else:
            categories = tuple(
                WeeklyReportCategory(
                    category_name=category.categoryName,
                    category_type=category.type,
                    is_base=category.isBase,
                    items=tuple(
                        WeeklyReportItem(
                            item_id=item.itemId,
                            item_name=item.itemName,
                            quality=item.quality,
                            total_num=item.totalNum,
                            icon=item.icon,
                        )
                        for item in category.items
                    ),
                )
                for category in report.categories
            )
        for category in categories:
            lines.append(category.category_name)
            for item in category.items:
                lines.append(item.item_name)

        sections = [{"name": category.category_name, "items": len(category.items)} for category in categories]
        resources = [self._font_resource()]
        for category in categories:
            for item in category.items:
                status = "provided" if self.resources.weekly_asset(item.item_id) is not None else "placeholder"
                resources.append(
                    {
                        "kind": "weekly_item",
                        "key": str(item.item_id),
                        "status": status,
                        "source": f"resources/weekly_item/item_{item.item_id}.png",
                    }
                )
        return self._write(image_bytes, lines=lines, resources=resources, sections=sections)

    async def render_calendar(
        self,
        snapshot: CalendarSnapshot,
        *,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
    ) -> RenderedEncyclopediaImage:
        contents = [
            CalendarContent(
                title=event.title,
                pic=event.pic,
                start_time=_value(event.start_at) if event.start_at else "",
                end_time=_value(event.end_at) if event.end_at else "",
            )
            for event in snapshot.events
        ]
        image_bytes = await _draw_calendar_card_bytes(contents, calendar_assets=self.resources.calendar_assets)
        lines = ["二重螺旋 · 活动日历"]
        for event in snapshot.events:
            lines.append(f"{event.title}: {_value(event.start_at) if event.start_at else ''} ~ {_value(event.end_at) if event.end_at else ''}")
            lines.append(event.title)
        resources = [self._font_resource()]
        for event in snapshot.events:
            asset = self.resources.calendar_asset(event.pic) or self.resources.calendar_asset(event.title)
            status = "provided" if asset is not None else "placeholder"
            resources.append(
                {
                    "kind": "calendar",
                    "key": event.title,
                    "status": status,
                    "source": f"resources/calendar/{event.pic}",
                }
            )
        sections = [{"name": "活动日历", "items": len(snapshot.events)}]
        return self._write(image_bytes, lines=lines, resources=resources, sections=sections)


__all__ = [
    "START_TIME",
    "CalendarContent",
    "EncyclopediaRenderer",
    "RenderedEncyclopediaImage",
    "TimeType",
    "_calendar_background",
    "_draw_stamina_card",
    "_draw_weekly_report_card",
    "_event_dates",
    "_event_image",
    "_event_payload",
    "_fmt_date",
    "_legacy_role_payload",
    "_load_banner",
    "_progress_ratio",
    "_value",
    "_weekly_item_payload",
    "draw_calendar_card",
    "draw_calendar_img",
    "draw_stamina_card",
    "draw_stamina_img",
    "draw_weekly_report_card",
    "draw_weekly_report_img",
    "get_date_range",
    "get_left_time_str",
    "get_time",
    "weekly_item_display_name",
]
