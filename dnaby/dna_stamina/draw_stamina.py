import random
import time
from io import BytesIO
from pathlib import Path

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
    DNARoleForToolRes,
    DNARoleShortNoteRes,
    RoleShowForTool,
)
from ..utils.database.models import DNABind
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image_utils import tint_image
from ..utils.msgs.notify import (
    dna_not_found,
    dna_peek_blocked,
    dna_token_invalid,
    dna_uid_invalid,
)
from ..utils.session import EventContext, Sender
from ..utils.utils import get_using_id, is_peek_blocked, is_uid_hidden

TEXT_PATH = Path(__file__).parent / "texture2d"
_RENDERER = HtmlRenderer()


def get_bg_list() -> Path:
    bg_path = TEXT_PATH / "bg"
    bg_list = [path for path in bg_path.iterdir() if path.suffix.lower() in (".jpg", ".png", ".webp")]
    return random.choice(bg_list)


def _progress_ratio(current: int, total: int) -> float:
    return min(current / total, 1) if total else 0


async def _draw_stamina_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    short_note_info: DNARoleShortNoteRes,
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
                tint_image(Image.open(TEXT_PATH / f"icon{index}.png"), (240, 230, 140)),
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
                    "state": "已完成" if is_done else format_seconds(int(draft.endTime) - now),
                }
            )

    return await _RENDERER.render(
        "cards/stamina.html.j2",
        {
            "background": image_data_uri(get_bg_list()),
            "drafts": drafts,
            "divider": image_data_uri(TEXT_PATH / "div.png"),
            "foreground": image_data_uri(TEXT_PATH / "fg.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "header": header,
            "header_background": image_data_uri(TEXT_PATH / "../../utils/texture2d/avatar_title_bg.png"),
            "bar_background": image_data_uri(TEXT_PATH / "bar_bg2.png"),
            "success": image_data_uri(TEXT_PATH / "success.png"),
            "running": image_data_uri(TEXT_PATH / "running.png"),
            "draft_background": image_data_uri(TEXT_PATH / "draft_bg.png"),
            "height": 1100,
            "notes": notes,
            "width": 2000,
        },
        RenderSpec(width=2000, height=1100, full_page=True, image_format="jpeg"),
    )


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


def format_seconds(seconds: float) -> str:
    hours = int(seconds // 3600)
    minute = int((seconds % 3600) // 60)
    second = int(seconds % 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}"


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



