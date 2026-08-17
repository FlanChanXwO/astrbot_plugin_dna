"""签到日历渲染边界，复用 DNAUID 原版绘制核心。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from ...entry.event import EventActor
from ...modules.checkin.contracts import CheckinCalendarData
from ..resources.encyclopedia import EncyclopediaResourceStore


@dataclass(frozen=True, slots=True)
class RenderedCheckinImage:
    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, object], ...]


class CheckinRenderer:
    """将 typed 快照无损还原为 legacy 模型并绘制原版签到卡。"""

    def __init__(self, output_dir: str | Path, resources: EncyclopediaResourceStore) -> None:
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
        from dnaby.dna_sign.draw_sign import _draw_sign_calendar
        from dnaby.utils.api.model import (
            DNACalendarSignRes,
            DNARoleForToolRes,
            DNATaskProcessRes,
        )
        from dnaby.utils.session import EventContext

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
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"checkin-{uuid.uuid4().hex}.png"
        image.save(path, format="PNG")
        lines = (
            role.role_name,
            f"社区累计签到: {data.total_sign_in_days}",
            f"游戏累计签到: {data.calendar.signin_time or 0}",
        )
        return RenderedCheckinImage(
            path=path,
            width=image.width,
            height=image.height,
            text_lines=lines,
            resources=({"kind": "sign_calendar", "status": "legacy"},),
            sections=(
                {"name": "社区任务", "items": len(task_process.dailyTask)},
                {"name": "游戏签到", "items": len(sign_data.dayAward)},
            ),
        )


__all__ = ["CheckinRenderer", "RenderedCheckinImage"]
