"""便签、周报和日历的确定性 Pillow 渲染器。

渲染器只消费 typed snapshot 和运行期资源索引。画布高度按完整数据动态计算，PNG
元数据保存完整文本、布局段和素材状态，便于不依赖像素 hash 的行为回归审查。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from ...entry.event import EventActor
from ...modules.encyclopedia.contracts import (
    CalendarSnapshot,
    PlayerShortNote,
    WeeklyReport,
)
from ..resources.encyclopedia import EncyclopediaResourceStore
from .fonts import load_runtime_font

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class RenderedEncyclopediaImage:
    """渲染结果及可审查的非框架元数据。"""

    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=SHANGHAI_TZ)
        else:
            value = value.astimezone(SHANGHAI_TZ)
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _timestamp(value: datetime | None) -> str:
    """按 legacy 锻造模型恢复秒时间戳字符串。"""

    return "" if value is None else str(int(value.timestamp()))


def _legacy_role_payload(role: Any) -> dict[str, Any]:
    """把共用 RoleOverview 还原成 DNARoleForToolRes 的嵌套结构。"""

    role_show = role.model_dump(by_alias=True)
    role_show.pop("achievementTotal", None)
    role_show["roleId"] = role.role_id
    role_show["roleAchv"] = {"total": role.achievement_total}
    return {"roleInfo": {"roleShow": role_show}}


class EncyclopediaRenderer:
    """生成完整资料卡片的运行期 PNG。"""

    def __init__(self, output_dir: str | Path, resources: EncyclopediaResourceStore) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return load_runtime_font(self.resources.font_path, size)

    def _font_resource(self) -> dict[str, str]:
        return {
            "kind": "font",
            "key": "dna_fonts",
            "status": self.resources.font_status,
            "source": "fonts/dna_fonts.ttf" if self.resources.font_path is not None else "",
        }

    @staticmethod
    def _lines_for_role(role: Any) -> list[str]:
        if role is None:
            return []
        lines = [role.role_name, f"等级: {_value(role.level)}", f"总成就数: {role.achievement_total}"]
        lines.extend(f"{item.param_key}: {item.param_value}" for item in role.params)
        return lines

    def _write(
        self,
        image: Image.Image,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
    ) -> RenderedEncyclopediaImage:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"encyclopedia-{uuid.uuid4().hex}.png"
        metadata = PngInfo()
        metadata.add_text("dnaby.text", "\n".join(lines))
        metadata.add_text(
            "dnaby.layout",
            json.dumps(
                {"width": image.width, "height": image.height, "sections": sections},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        metadata.add_text(
            "dnaby.resources",
            json.dumps(resources, ensure_ascii=False, separators=(",", ":")),
        )
        # legacy GsCore 先以 JPEG quality=85 编码再转回 PNG；保留该有损往返以匹配像素。
        jpeg_buffer = BytesIO()
        image.convert("RGB").save(jpeg_buffer, format="JPEG", quality=85)
        jpeg_buffer.seek(0)
        with Image.open(jpeg_buffer) as decoded:
            decoded.convert("RGBA").save(path, format="PNG", pnginfo=metadata)
        return RenderedEncyclopediaImage(
            path=path,
            width=image.width,
            height=image.height,
            text_lines=tuple(lines),
            resources=tuple(resources),
            sections=tuple(sections),
        )

    def _header(self, draw: ImageDraw.ImageDraw, title: str) -> None:
        draw.text((48, 36), title, fill=(255, 215, 145, 255), font=self._font(36))

    def _section(self, draw: ImageDraw.ImageDraw, y: int, title: str) -> None:
        draw.rounded_rectangle((36, y, 1164, y + 44), radius=10, fill=(64, 79, 113, 255))
        draw.text((56, y + 22), title, fill=(250, 250, 250, 255), font=self._font(24), anchor="lm")

    def _draw_lines(self, draw: ImageDraw.ImageDraw, lines: list[str], y: int, *, color=(224, 230, 240, 255)) -> int:
        for line in lines:
            draw.text((60, y), line, fill=color, font=self._font(21))
            y += 34
        return y

    async def render_stamina(
        self,
        snapshot: PlayerShortNote,
        *,
        actor: EventActor,
        target_user_id: str | None = None,
        uid: str,
        uid_hidden: bool,
    ) -> RenderedEncyclopediaImage:
        """把 typed 快照无损还原到 legacy 便签绘制模型。"""

        from dnaby.dna_stamina.draw_stamina import draw_stamina_card
        from dnaby.utils.api.model import DNARoleForToolRes, DNARoleShortNoteRes
        from dnaby.utils.session import EventContext

        role = snapshot.role_overview
        if role is None:
            raise ValueError("便签缺少角色概览，无法绘制 legacy 卡片")

        short_note = DNARoleShortNoteRes.model_validate(
            {
                "rougeLikeRewardCount": snapshot.rouge_like_reward_count,
                "rougeLikeRewardTotal": snapshot.rouge_like_reward_total,
                "currentTaskProgress": snapshot.current_task_progress,
                "maxDailyTaskProgress": snapshot.max_daily_task_progress,
                "hardBossRewardCount": snapshot.hard_boss_reward_count,
                "hardBossRewardTotal": snapshot.hard_boss_reward_total,
                "dungeonReward": snapshot.dungeon_reward,
                "dungeonRewardTotal": snapshot.dungeon_reward_total,
                "draftInfo": {
                    "draftDoingInfo": [
                        {
                            "draftCompleteNum": draft.draft_complete_num,
                            "draftDoingNum": draft.draft_doing_num,
                            "startTime": _timestamp(draft.start_at),
                            "endTime": _timestamp(draft.end_at),
                            "productName": draft.product_name or None,
                        }
                        for draft in snapshot.drafts
                    ],
                    "draftDoingNum": snapshot.draft_doing_num,
                    "draftMaxNum": snapshot.draft_max_num,
                },
            },
        )
        role_info = DNARoleForToolRes.model_validate(
            _legacy_role_payload(role),
        )
        resolved_user_id = target_user_id or actor.user_id
        ctx = EventContext(
            user_id=resolved_user_id,
            bot_id=actor.bot_id,
            group_id=actor.group_id or "",
            at=resolved_user_id,
            unified_msg_origin=actor.unified_msg_origin or "",
        )
        image = await draw_stamina_card(
            short_note,
            role_info,
            ctx=ctx,
            avatar_user_id=resolved_user_id,
            uid_hidden=uid_hidden,
        )

        lines = ["二重螺旋 · 实时便签"]
        lines.extend(self._lines_for_role(snapshot.role_overview))
        progress = (
            ("备忘手记", snapshot.current_task_progress, snapshot.max_daily_task_progress),
            ("迷津", snapshot.rouge_like_reward_count, snapshot.rouge_like_reward_total),
            ("梦魇残声", snapshot.hard_boss_reward_count, snapshot.hard_boss_reward_total),
            ("竞逐", snapshot.dungeon_reward, snapshot.dungeon_reward_total),
        )
        lines.append("便签进度")
        lines.extend(f"{name}: {current}/{total}" for name, current, total in progress)
        lines.append("锻造")
        lines.extend(
            f"{draft.product_name}: {_value(draft.start_at)} ~ {_value(draft.end_at)} · "
            f"{'已完成' if draft.completed else '进行中'}"
            for draft in snapshot.drafts
        )

        resources = [
            self._font_resource(),
            {
                "kind": "stamina_card",
                "key": "background",
                "source": "dnaby/dna_stamina/texture2d",
                "status": "legacy",
            },
        ]
        sections = [
            {"name": "角色概览", "items": 1},
            {"name": "便签进度", "items": len(progress)},
            {"name": "锻造", "items": len(snapshot.drafts)},
        ]
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def render_weekly_report(
        self,
        report: WeeklyReport,
        *,
        actor: EventActor,
        target_user_id: str | None = None,
        uid: str,
        uid_hidden: bool,
    ) -> RenderedEncyclopediaImage:
        """把 typed 周报无损还原到 legacy 动态素材卡片。"""

        from dnaby.dna_weekly_report.draw_weekly_report import draw_weekly_report_card
        from dnaby.utils.api.model import DNAItemWeeklyReportRes, DNARoleForToolRes
        from dnaby.utils.session import EventContext

        role = report.role_overview
        if role is None:
            raise ValueError("周报缺少角色概览，无法绘制 legacy 卡片")

        legacy_report = DNAItemWeeklyReportRes.model_validate(
            {
                "categories": [
                    {
                        "categoryName": category.category_name,
                        "isBase": category.is_base,
                        "type": category.category_type,
                        "items": [
                            {
                                "icon": item.icon,
                                "itemId": item.item_id,
                                "itemName": item.item_name,
                                "quality": item.quality,
                                "totalNum": item.total_num,
                            }
                            for item in category.items
                        ],
                    }
                    for category in report.categories
                ],
                "startDate": report.start_date,
                "endDate": report.end_date,
                "weekType": report.week_type,
            },
        )
        role_show = DNARoleForToolRes.model_validate(
            _legacy_role_payload(role),
        ).roleInfo.roleShow
        resolved_user_id = target_user_id or actor.user_id
        ctx = EventContext(
            user_id=resolved_user_id,
            bot_id=actor.bot_id,
            group_id=actor.group_id or "",
            at=resolved_user_id,
            unified_msg_origin=actor.unified_msg_origin or "",
        )
        item_assets = {
            item.item_id: asset
            for category in report.categories
            for item in category.items
            if (asset := self.resources.weekly_asset(item.item_id)) is not None
        }
        image = await draw_weekly_report_card(
            legacy_report,
            role_show,
            ctx=ctx,
            avatar_user_id=resolved_user_id,
            uid_hidden=uid_hidden,
            item_assets=item_assets,
        )

        label = "本周周报" if report.week_type == 1 else "上周周报"
        lines = [label, f"{report.start_date} ~ {report.end_date}"]
        lines.extend(self._lines_for_role(report.role_overview))
        sections: list[dict[str, Any]] = []
        resources: list[dict[str, str]] = [self._font_resource()]
        for category in report.categories:
            lines.append(category.category_name)
            for item in category.items:
                lines.append(f"{item.item_name}: × {item.total_num}")
                asset = self.resources.weekly_asset(item.item_id)
                resources.append(
                    {
                        "kind": "weekly_item",
                        "key": str(item.item_id),
                        "source": item.icon,
                        "status": "provided" if asset is not None else "placeholder",
                    },
                )

        cursor_y = 400
        for category in report.categories:
            rows = max(1, (len(category.items) + 4) // 5)
            category_height = 70 + rows * 230 + 20
            sections.append(
                {
                    "name": category.category_name,
                    "start": cursor_y,
                    "height": category_height,
                    "items": len(category.items),
                },
            )
            cursor_y += category_height
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def render_calendar(
        self,
        snapshot: CalendarSnapshot,
        *,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
    ) -> RenderedEncyclopediaImage:
        """把 typed 日历无损还原到 legacy 双栏活动卡。"""

        from dnaby.dna_calendar.draw_calendar_card import (
            CalendarContent,
            draw_calendar_card,
        )

        del actor, target_user_id
        content = [
            CalendarContent(
                title=event.title,
                pic=event.pic,
                start_time=_value(event.start_at),
                end_time=_value(event.end_at),
            )
            for event in snapshot.events
        ]
        calendar_assets = {
            event.pic: asset
            for event in snapshot.events
            if (asset := self.resources.calendar_asset(event.pic)) is not None
        }
        image = await draw_calendar_card(
            content,
            calendar_assets=calendar_assets,
        )

        lines = ["二重螺旋 · 活动日历"]
        resources: list[dict[str, str]] = [self._font_resource()]
        sections: list[dict[str, Any]] = []
        event_start_y = 780
        for index, event in enumerate(snapshot.events):
            lines.append(
                f"{event.title}: {_value(event.start_at)} ~ {_value(event.end_at)}"
            )
            asset = self.resources.calendar_asset(event.pic)
            resources.append(
                {
                    "kind": "calendar",
                    "key": event.title,
                    "source": event.pic,
                    "status": "provided" if asset is not None else "placeholder",
                },
            )
            sections.append(
                {
                    "name": event.title,
                    "start": event_start_y + index // 2 * 170,
                    "height": 170,
                },
            )
        return self._write(image, lines=lines, resources=resources, sections=sections)


__all__ = ["EncyclopediaRenderer", "RenderedEncyclopediaImage"]
