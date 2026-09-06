"""签到日历与签到报告 HTML/T2I 渲染器。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


from ...entry.event import EventActor
from ...modules.checkin.contracts import CheckinCalendarData
from ...utils.api.model import (
    DNACalendarSignRes,
    DNARoleForToolRes,
    DNATaskProcessRes,
    RoleShowForTool,
)
from ...utils.image import download_pic_from_url
from ...utils.resource.RESOURCE_PATH import SIGN_PATH
from ...utils.session import EventContext
from ..resources.encyclopedia import EncyclopediaResourceStore
from .artifact import RenderedArtifact
from .artifact_store import write_rendered_artifact
from .assets import font_data_uri, image_data_uri, pil_image_data_uri
from .payloads import build_profile_header
from .renderer import HtmlRenderer
from .spec import RenderSpec

_RENDERER = HtmlRenderer()
RESOURCES_DIR = Path(__file__).parents[2] / "resources"
BACKGROUND_PATH = RESOURCES_DIR / "textures" / "common" / "bg1.jpg"
TEXT_PATH = RESOURCES_DIR / "textures" / "sign"
COMMON_PATH = RESOURCES_DIR / "textures" / "common"
FONT_ORIGIN_PATH = RESOURCES_DIR / "fonts" / "dna_fonts.ttf"


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
            icon = pil_image_data_uri(
                await download_pic_from_url(SIGN_PATH, award.iconUrl, size=(140, 140))
            )
        return {
            "amount": award.awardNum if award else 0,
            "current": day == (sign_data.signinTime or 0),
            "day": day,
            "icon": icon,
            "signed": day <= (sign_data.signinTime or 0),
        }

    over_days = sign_data.period.overDays if sign_data.period else 30
    awards = list(
        await asyncio.gather(*(build_award(day) for day in range(1, over_days + 1)))
    )

    height = (
        30
        + 270
        + 120
        + 100 * 2
        + 50
        + (60 * len(tasks) + 20 if tasks else 0)
        + 240 * ((over_days + 6) // 7)
    )

    return await _RENDERER.render(
        "cards/sign_calendar.html.j2",
        {
            "achievements": achievement_info,
            "awards": awards,
            "background": image_data_uri(BACKGROUND_PATH),
            "achievement_background": image_data_uri(TEXT_PATH / "bar.png"),
            "divider_background": image_data_uri(COMMON_PATH / "div.png"),
            "item_background": image_data_uri(TEXT_PATH / "item_BG.png"),
            "green": image_data_uri(TEXT_PATH / "green.png"),
            "red": image_data_uri(TEXT_PATH / "red.png"),
            "task_background": image_data_uri(TEXT_PATH / "line.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "header": header,
            "header_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "tasks": tasks,
            "width": 1300,
            "height": height,
        },
        RenderSpec(
            width=1300,
            height=height,
            full_page=True,
            output_format="jpeg",
        ),
    )


async def create_sign_info_image(text: str, theme: str = "blue") -> bytes:
    """以固定 600×250 HTML 卡片渲染群签到汇总。"""

    colors = {
        "blue": "#e6e6ff",
        "yellow": "#ffffe6",
        "pink": "#ffe6e6",
        "green": "#e6ffe6",
    }
    return await _RENDERER.render(
        "cards/sign_report.html.j2",
        {
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "lines": text[1:].split("\n"),
            "theme_color": colors.get(theme, colors["blue"]),
            "width": 600,
        },
        RenderSpec(width=600, height=250, full_page=False),
    )


@dataclass(frozen=True, slots=True)
class RenderedCheckinImage:
    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, object], ...]
    sidecar: Path | None = None
    manifest: Path | None = None
    media_type: str = "image/jpeg"


class CheckinRenderer:
    """将 typed 快照无损还原为 legacy 模型并绘制原版签到卡。"""

    def __init__(
        self, output_dir: str | Path, resources: EncyclopediaResourceStore
    ) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources

    async def render_calendar(
        self,
        data: CheckinCalendarData,
        *,
        actor: EventActor,
        target_user_id: str,
        uid_hidden: bool,
    ) -> RenderedCheckinImage:
        role = data.role_overview
        period = data.calendar.period
        if role is None or period is None:
            raise ValueError("签到日历缺少角色概览或签到周期")
        role_payload = role.model_dump(by_alias=True)
        role_payload.pop("achievementTotal", None)
        role_payload["roleAchv"] = {"total": role.achievement_total}
        role_show = DNARoleForToolRes.model_validate(
            {"roleInfo": {"roleShow": role_payload}},
        ).roleInfo.roleShow
        sign_data = DNACalendarSignRes.model_validate(
            {
                "todaySignin": data.calendar.today_signed,
                "userGoldNum": data.calendar.user_gold,
                "signinTime": data.calendar.signin_time,
                "period": {
                    "gameId": 0,
                    "retryCos": 0,
                    "retryTimes": 0,
                    "createTime": 0,
                    "id": period.period_id,
                    "name": period.name,
                    "overDays": period.over_days,
                    "startDate": period.start_date,
                    "endDate": period.end_date,
                },
                "dayAward": [
                    {
                        "gameId": 0,
                        "updateTime": 0,
                        "thirdProductId": "",
                        "createTime": 0,
                        "id": award.award_id,
                        "periodId": award.period_id,
                        "dayInPeriod": award.day_in_period,
                        "awardName": award.award_name,
                        "awardNum": award.award_num,
                        "iconUrl": award.icon_url,
                    }
                    for award in data.calendar.day_awards
                ],
            },
        )
        task_process = DNATaskProcessRes.model_validate(
            {
                "dailyTask": [
                    {
                        "remark": task.remark,
                        "completeTimes": task.complete_times,
                        "times": task.times,
                        "skipType": 0,
                        "gainExp": task.gain_exp,
                        "process": task.process,
                        "gainGold": task.gain_gold,
                    }
                    for task in (() if data.tasks is None else data.tasks.daily_tasks)
                ],
            },
        )
        ctx = EventContext(
            user_id=target_user_id,
            bot_id=actor.bot_id,
            group_id=actor.group_id or "",
            at=target_user_id,
            unified_msg_origin=actor.unified_msg_origin or "",
        )
        image_bytes = await _draw_sign_calendar(
            ctx,
            role_show,
            sign_data,
            task_process,
            data.total_sign_in_days,
            uid_hidden,
        )
        lines = (
            role.role_name,
            f"社区累计签到: {data.total_sign_in_days}",
            f"游戏累计签到: {data.calendar.signin_time or 0}",
        )
        resources = ({"kind": "sign_calendar", "status": "legacy"},)
        sections = (
            {"name": "社区任务", "items": len(task_process.dailyTask)},
            {"name": "游戏签到", "items": len(sign_data.dayAward)},
        )
        artifact = RenderedArtifact.from_bytes(
            image_bytes,
            media_type="image/jpeg",
            metadata={
                "dnaby.text": "\n".join(lines),
                "dnaby.layout": {
                    "width": 0,
                    "height": 0,
                    "sections": list(sections),
                },
                "dnaby.resources": list(resources),
            },
        )
        metadata = dict(artifact.metadata)
        metadata["dnaby.layout"] = {
            "width": artifact.width,
            "height": artifact.height,
            "sections": list(sections),
        }
        artifact = RenderedArtifact.from_bytes(
            image_bytes, media_type="image/jpeg", metadata=metadata
        )
        response = write_rendered_artifact(self.output_dir, artifact, prefix="checkin-")
        return RenderedCheckinImage(
            path=Path(response.image),
            width=artifact.width,
            height=artifact.height,
            text_lines=lines,
            resources=resources,
            sections=sections,
            sidecar=Path(response.sidecar) if response.sidecar else None,
            manifest=Path(response.manifest) if response.manifest else None,
            media_type=artifact.media_type,
        )


__all__ = [
    "CheckinRenderer",
    "RenderedCheckinImage",
    "_draw_sign_calendar",
    "create_sign_info_image",
]
