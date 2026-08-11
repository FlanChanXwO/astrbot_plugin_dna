"""便签、周报和日历的确定性 Pillow 渲染器。

渲染器只消费 typed snapshot 和运行期资源索引。画布高度按完整数据动态计算，PNG
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

from ...modules.encyclopedia.contracts import (
    CalendarSnapshot,
    PlayerShortNote,
    WeeklyReport,
)
from ..resources.encyclopedia import EncyclopediaResourceStore
from .fonts import load_runtime_font


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
        return value.astimezone().strftime("%Y-%m-%d %H:%M") if value.tzinfo else value.strftime("%Y-%m-%d %H:%M")
    return str(value)


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
        image.convert("RGBA").save(path, format="PNG", pnginfo=metadata)
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

    def render_stamina(self, snapshot: PlayerShortNote) -> RenderedEncyclopediaImage:
        """渲染便签，完整保留角色参数和所有锻造槽位。"""

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

        height = max(620, 150 + len(lines) * 34)
        image = Image.new("RGBA", (1200, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        resources = [
            self._font_resource(),
            {
                "kind": "stamina_card",
                "key": "background",
                "source": "",
                "status": "generated",
            },
        ]
        y = 100
        sections: list[dict[str, Any]] = []
        role_lines = self._lines_for_role(snapshot.role_overview)
        if role_lines:
            self._section(draw, y, "角色概览")
            start = y
            y = self._draw_lines(draw, role_lines, y + 62)
            sections.append({"name": "角色概览", "start": start, "height": y - start})
        self._section(draw, y, "便签进度")
        start = y
        y = self._draw_lines(draw, [f"{name}: {current}/{total}" for name, current, total in progress], y + 62)
        sections.append({"name": "便签进度", "start": start, "height": y - start})
        self._section(draw, y, "锻造")
        start = y
        draft_lines = [
            f"{draft.product_name}: {_value(draft.start_at)} ~ {_value(draft.end_at)} · "
            f"{'已完成' if draft.completed else '进行中'}"
            for draft in snapshot.drafts
        ] or ["暂无锻造记录"]
        y = self._draw_lines(draw, draft_lines, y + 62)
        sections.append({"name": "锻造", "start": start, "height": y - start})
        return self._write(image, lines=lines, resources=resources, sections=sections)

    def render_weekly_report(self, report: WeeklyReport) -> RenderedEncyclopediaImage:
        """渲染周报，遍历所有分类和资源项，不截断名称。"""

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

        item_rows = sum(max(1, len(category.items)) for category in report.categories)
        height = max(520, 190 + len(report.categories) * 70 + item_rows * 62)
        image = Image.new("RGBA", (1200, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, f"二重螺旋 · {label}")
        y = 100
        role_lines = self._lines_for_role(report.role_overview)
        if role_lines:
            self._section(draw, y, "角色概览")
            start = y
            y = self._draw_lines(draw, role_lines, y + 62)
            sections.append({"name": "角色概览", "start": start, "height": y - start})
        draw.text((60, y + 8), f"周期: {report.start_date} ~ {report.end_date}", fill=(224, 230, 240, 255), font=self._font(22))
        y += 50
        for category in report.categories:
            self._section(draw, y, category.category_name)
            start = y
            item_lines = [f"{item.item_name}: × {item.total_num}" for item in category.items]
            if not item_lines:
                item_lines = ["本周暂无相关资源获取"]
            y = self._draw_lines(draw, item_lines, y + 62)
            sections.append(
                {
                    "name": category.category_name,
                    "start": start,
                    "height": y - start,
                    "items": len(category.items),
                },
            )
        return self._write(image, lines=lines, resources=resources, sections=sections)

    def render_calendar(self, snapshot: CalendarSnapshot) -> RenderedEncyclopediaImage:
        """渲染完整活动日历；缺失时间只显示已有字段。"""

        lines = ["二重螺旋 · 活动日历"]
        resources: list[dict[str, str]] = [self._font_resource()]
        for event in snapshot.events:
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

        height = max(430, 130 + max(1, len(snapshot.events)) * 92)
        image = Image.new("RGBA", (1200, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        y = 100
        sections: list[dict[str, Any]] = []
        for event in snapshot.events:
            self._section(draw, y, event.title)
            start = y
            detail = [
                f"开始: {_value(event.start_at)}" if event.start_at is not None else "开始: 未提供",
                f"结束: {_value(event.end_at)}" if event.end_at is not None else "结束: 未提供",
                f"素材: {event.pic}" if event.pic else "素材: 未提供",
            ]
            y = self._draw_lines(draw, detail, y + 62)
            sections.append({"name": event.title, "start": start, "height": y - start})
        if not snapshot.events:
            y = self._draw_lines(draw, ["暂无活动数据"], y + 62)
        return self._write(image, lines=lines, resources=resources, sections=sections)


__all__ = ["EncyclopediaRenderer", "RenderedEncyclopediaImage"]
