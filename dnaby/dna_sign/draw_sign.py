import asyncio
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
    DNACalendarSignRes,
    DNARoleForToolRes,
    DNATaskProcessRes,
    RoleShowForTool,
)
from ..utils.database.models import DNABind
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image import download_pic_from_url
from ..utils.msgs.notify import dna_not_found
from ..utils.resource.RESOURCE_PATH import SIGN_PATH
from ..utils.session import EventContext, Sender
from ..utils.utils import is_uid_hidden

_RENDERER = HtmlRenderer()
BACKGROUND_PATH = Path(__file__).parents[1] / "utils" / "texture2d" / "bg1.jpg"
TEXT_PATH = Path(__file__).parent / "texture2d"


async def _draw_sign_calendar(
    ctx: EventContext,
    role_show: RoleShowForTool,
    sign_data: DNACalendarSignRes,
    task_process: DNATaskProcessRes,
    bbs_total_sign_in_day: int,
    uid_hidden: bool = False,
) -> bytes:
    """组装签到日历 payload，保留每日奖励和社区任务的完整条目。"""

    header = await build_profile_header(
        ctx,
        role_show.roleId,
        role_show.roleName,
        user_level=role_show.level,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    achievement_info = [
        {"label": "皎皎积分", "value": str(sign_data.userGoldNum or 0)},
        {"label": "社区累计签到", "value": str(bbs_total_sign_in_day)},
        {"label": "游戏累计签到", "value": str(sign_data.signinTime or 0)},
    ]
    achievement_info.extend(
        {"label": item.paramKey, "value": item.paramValue}
        for item in role_show.params
        if item.paramKey in ("总活跃天数",)
    )
    tasks = [
        {
            "done": task.completeTimes >= task.times,
            "progress": max(0.0, min(task.process, 1.0)),
            "remark": task.remark,
        }
        for task in task_process.dailyTask
    ]
    award_dict = {award.dayInPeriod: award for award in sign_data.dayAward}
    async def build_award(day: int) -> dict[str, object]:
        award = award_dict.get(day)
        icon = None
        if award:
            icon = pil_image_data_uri(await download_pic_from_url(SIGN_PATH, award.iconUrl, size=(140, 140)))
        return {
            "amount": award.awardNum if award else 0,
            "current": day == (sign_data.signinTime or 0),
            "day": day,
            "icon": icon,
            "signed": day <= (sign_data.signinTime or 0),
        }

    awards = list(await asyncio.gather(*(build_award(day) for day in range(1, sign_data.period.overDays + 1))))

    return await _RENDERER.render(
        "cards/sign_calendar.html.j2",
        {
            "achievements": achievement_info,
            "awards": awards,
            "background": image_data_uri(BACKGROUND_PATH),
            "achievement_background": image_data_uri(TEXT_PATH / "bar.png"),
            "divider_background": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "div.png"),
            "item_background": image_data_uri(TEXT_PATH / "item_BG.png"),
            "green": image_data_uri(TEXT_PATH / "green.png"),
            "red": image_data_uri(TEXT_PATH / "red.png"),
            "task_background": image_data_uri(TEXT_PATH / "line.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"),
            "header": header,
            "header_background": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "avatar_title_bg.png"),
            "tasks": tasks,
            "width": 1300,
            "height": 30 + 270 + 120 + 100 * 2 + 50 + (60 * len(tasks) + 20 if tasks else 0) + 240 * ((sign_data.period.overDays + 6) // 7),
        },
        RenderSpec(width=1300, height=30 + 270 + 120 + 100 * 2 + 50 + (60 * len(tasks) + 20 if tasks else 0) + 240 * ((sign_data.period.overDays + 6) // 7), full_page=True, image_format="jpeg"),
    )


async def draw_sign_calendar(sender: Sender, ctx: EventContext):
    uid = await DNABind.get_uid_by_game(ctx.user_id, ctx.bot_id)
    if not uid:
        return
    dna_user = await dna_api.get_dna_user(uid, ctx.user_id, ctx.bot_id)
    if not dna_user:
        return
    have_sign_in_resp = await dna_api.have_sign_in(dna_user)
    if not have_sign_in_resp.is_success or not isinstance(have_sign_in_resp.data, dict):
        return
    bbs_total_sign_in_day = have_sign_in_resp.data.get("totalSignInDay", 0)
    sign_resp = await dna_api.sign_calendar(dna_user)
    if not sign_resp.is_success:
        return
    sign_data = DNACalendarSignRes.model_validate(sign_resp.data if isinstance(sign_resp.data, dict) else {})
    task_process_resp = await dna_api.get_task_process(dna_user)
    if not task_process_resp.is_success:
        return
    task_process = DNATaskProcessRes.model_validate(task_process_resp.data)
    default_role = await dna_api.get_default_role_for_tool(dna_user)
    if not default_role.is_success:
        await dna_not_found(sender, ctx, "角色列表信息")
        return
    role_show = DNARoleForToolRes.model_validate(default_role.data).roleInfo.roleShow
    uid_hidden = await is_uid_hidden(ctx.user_id, ctx.bot_id, ctx.group_id)
    await sender.send(
        await _draw_sign_calendar(ctx, role_show, sign_data, task_process, bbs_total_sign_in_day, uid_hidden)
    )
