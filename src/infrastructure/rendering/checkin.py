"""签到日历的确定性 Pillow 渲染器。

渲染器只消费 typed ``CheckinCalendarData``。画布高度按完整数据动态计算，PNG
元数据保存完整文本、布局段和素材状态，便于不依赖像素 hash 的行为回归审查。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from ...modules.checkin.contracts import CheckinCalendarData, SignStatus
from ...modules.checkin import messages
from ..resources.encyclopedia import EncyclopediaResourceStore
from .fonts import load_runtime_font

_CALENDAR_COLS = 7


@dataclass(frozen=True, slots=True)
class RenderedCheckinImage:
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
            return value.strftime("%Y-%m-%d %H:%M")
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value)


class CheckinRenderer:
    """生成签到日历的运行期 PNG。"""

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

    def _write(
        self,
        image: Image.Image,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
    ) -> RenderedCheckinImage:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"checkin-{uuid.uuid4().hex}.png"
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
        image.convert("RGBA").save(path, format="PNG", pnginfo=metadata)
        return RenderedCheckinImage(
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
        draw.rounded_rectangle((36, y, 1264, y + 44), radius=10, fill=(64, 79, 113, 255))
        draw.text((56, y + 22), title, fill=(250, 250, 250, 255), font=self._font(24), anchor="lm")

    def _draw_lines(self, draw: ImageDraw.ImageDraw, lines: list[str], y: int, *, color=(224, 230, 240, 255)) -> int:
        for line in lines:
            draw.text((60, y), line, fill=color, font=self._font(21))
            y += 34
        return y

    def _role_lines(self, data: CheckinCalendarData) -> list[str]:
        role = data.role_overview
        if role is None:
            return []
        lines = [role.role_name, f"等级: {_value(role.level)}", f"总成就数: {role.achievement_total}"]
        lines.extend(f"{item.param_key}: {item.param_value}" for item in role.params)
        return lines

    def render_calendar(self, data: CheckinCalendarData) -> RenderedCheckinImage:
        """渲染签到日历，完整保留角色、签到状态、社区任务和逐日奖励。"""

        calendar = data.calendar
        lines = ["二重螺旋 · 签到日历"]
        lines.extend(self._role_lines(data))
        gold = calendar.user_gold if calendar.user_gold is not None else 0
        signed_days = calendar.signin_time if calendar.signin_time is not None else 0
        lines.append(f"皎皎积分: {gold}")
        lines.append(f"社区累计签到: {data.total_sign_in_days}")
        lines.append(f"游戏累计签到: {signed_days}")
        lines.append(
            f"今日签到: {messages.sign_status(SignStatus.DONE) if calendar.today_signed else messages.sign_status(SignStatus.SKIP)}"
        )
        lines.append("社区任务")
        task_lines: list[str] = []
        if data.tasks is not None:
            for task in data.tasks.daily_tasks:
                task_lines.append(f"{task.remark}: {task.complete_times}/{task.times}")
        lines.extend(task_lines or ["暂无社区任务"])
        lines.append("游戏签到奖励")
        award_lines = [
            f"第{item.day_in_period}天: {item.award_name} × {item.award_num}"
            for item in calendar.day_awards
        ]
        lines.extend(award_lines or ["暂无签到奖励"])

        period = calendar.period
        rows = max(1, (period.over_days if period is not None else 0) // _CALENDAR_COLS + 1)
        task_rows = max(1, len(data.tasks.daily_tasks) if data.tasks is not None else 0)
        height = max(520, 160 + len(self._role_lines(data)) * 34 + 160 + task_rows * 70 + rows * 120)
        image = Image.new("RGBA", (1300, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        resources: list[dict[str, str]] = [self._font_resource()]
        for award in calendar.day_awards:
            resources.append(
                {
                    "kind": "sign_award",
                    "key": str(award.day_in_period),
                    "source": award.icon_url,
                    "status": "placeholder",
                },
            )
        y = 100
        sections: list[dict[str, Any]] = []
        role_lines = self._role_lines(data)
        if role_lines:
            self._section(draw, y, "角色概览")
            start = y
            y = self._draw_lines(draw, role_lines, y + 62)
            sections.append({"name": "角色概览", "start": start, "height": y - start})
        self._section(draw, y, "签到信息")
        start = y
        info_lines = [
            f"皎皎积分: {gold}",
            f"社区累计签到: {data.total_sign_in_days}",
            f"游戏累计签到: {signed_days}",
            f"今日签到: {messages.sign_status(SignStatus.DONE) if calendar.today_signed else messages.sign_status(SignStatus.SKIP)}",
        ]
        y = self._draw_lines(draw, info_lines, y + 62)
        sections.append({"name": "签到信息", "start": start, "height": y - start})
        self._section(draw, y, "社区任务")
        start = y
        y = self._draw_lines(draw, task_lines or ["暂无社区任务"], y + 62)
        sections.append({"name": "社区任务", "start": start, "height": y - start})
        self._section(draw, y, "游戏签到奖励")
        start = y
        grid_lines: list[str] = []
        if period is not None:
            by_day = {item.day_in_period: item for item in calendar.day_awards}
            for day in range(1, period.over_days + 1):
                signed = day <= signed_days
                current = day == signed_days and not (calendar.today_signed or False)
                award = by_day.get(day)
                suffix = ""
                if current:
                    suffix = " (今日)"
                elif signed:
                    suffix = " ✓"
                if award is not None:
                    grid_lines.append(f"第{day}天: {award.award_name} × {award.award_num}{suffix}")
                else:
                    grid_lines.append(f"第{day}天{suffix}")
        y = self._draw_lines(draw, grid_lines or ["暂无签到奖励"], y + 62)
        sections.append({"name": "游戏签到奖励", "start": start, "height": y - start})
        return self._write(image, lines=lines, resources=resources, sections=sections)


__all__ = ["CheckinRenderer", "RenderedCheckinImage"]
