"""密函与公告的确定性 Pillow 渲染器。

渲染器只消费 typed notices 快照与运行期资源索引。画布高度按完整数据动态计算，
PNG 元数据保存完整文本、布局段和素材状态，便于不依赖像素 hash 的行为回归审查。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from ...modules.notices.contracts import AnnDetail, AnnSnapshot, MhSnapshot
from ..resources.encyclopedia import EncyclopediaResourceStore
from .fonts import load_runtime_font


@dataclass(frozen=True, slots=True)
class RenderedNoticesImage:
    """渲染结果及可审查的非框架元数据。"""

    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]


class NoticesRenderer:
    """生成密函与公告卡片的运行期 PNG。"""

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
    ) -> RenderedNoticesImage:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"notices-{uuid.uuid4().hex}.png"
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
        return RenderedNoticesImage(
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

    def render_mh(self, snapshot: MhSnapshot) -> RenderedNoticesImage:
        """渲染当前小时段密函，完整保留每个类型下的全部委托。"""

        lines = ["二重螺旋 · 密函"]
        for section in snapshot.sections:
            lines.append(f"{section.type_name}:")
            lines.extend(f"{item.name} (id={item.instance_id})" for item in section.instances)
        height = max(430, 130 + sum(1 + len(section.instances) for section in snapshot.sections) * 34)
        image = Image.new("RGBA", (1300, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        resources: list[dict[str, str]] = [self._font_resource()]
        y = 100
        sections: list[dict[str, Any]] = []
        for section in snapshot.sections:
            self._section(draw, y, section.type_name)
            start = y
            item_lines = [f"{item.name} (id={item.instance_id})" for item in section.instances]
            y = self._draw_lines(draw, item_lines or ["暂无委托"], y + 62)
            sections.append(
                {
                    "name": section.type_name,
                    "start": start,
                    "height": y - start,
                    "items": len(section.instances),
                },
            )
        return self._write(image, lines=lines, resources=resources, sections=sections)

    def render_ann_list(self, snapshot: AnnSnapshot) -> RenderedNoticesImage:
        """渲染公告列表，按序号展示全部公告标题与时间。"""

        lines = ["二重螺旋 · 公告列表"]
        resources: list[dict[str, str]] = [self._font_resource()]
        for index, post in enumerate(snapshot.posts, start=1):
            lines.append(f"{index}. {post.title}")
            if post.time:
                lines.append(f"   {post.time}")
            resources.append(
                {
                    "kind": "ann_preview",
                    "key": post.post_id,
                    "source": post.preview,
                    "status": "provided" if post.preview else "placeholder",
                },
            )
        height = max(430, 130 + max(1, len(snapshot.posts)) * 70)
        image = Image.new("RGBA", (1300, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        sections: list[dict[str, Any]] = []
        y = 100
        self._section(draw, y, "公告")
        start = y
        list_lines: list[str] = []
        for index, post in enumerate(snapshot.posts, start=1):
            list_lines.append(f"{index}. {post.title}")
            if post.time:
                list_lines.append(f"   {post.time}")
        y = self._draw_lines(draw, list_lines or ["暂无公告"], y + 62)
        sections.append({"name": "公告", "start": start, "height": y - start, "items": len(snapshot.posts)})
        return self._write(image, lines=lines, resources=resources, sections=sections)

    def render_ann_detail(self, detail: AnnDetail) -> RenderedNoticesImage:
        """渲染一篇公告详情，保留全部文本块；图片块标记为 placeholder 资源。"""

        lines = ["二重螺旋 · 公告详情", detail.title]
        resources: list[dict[str, str]] = [self._font_resource()]
        text_lines: list[str] = []
        for index, block in enumerate(detail.blocks):
            if block.kind == "text":
                text_lines.append(block.text)
                continue
            resources.append(
                {
                    "kind": "ann_image",
                    "key": f"{detail.post_id}-{index}",
                    "source": block.image_url,
                    "status": "placeholder",
                },
            )
            text_lines.append("[图片]")
        lines.extend(text_lines)
        height = max(430, 150 + len(detail.title) // 30 * 34 + len(text_lines) * 34)
        image = Image.new("RGBA", (1300, height), (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        self._header(draw, lines[0])
        y = 100
        sections: list[dict[str, Any]] = []
        self._section(draw, y, detail.title[:40] or "公告")
        start = y
        y = self._draw_lines(draw, text_lines or ["（无文本内容）"], y + 62)
        sections.append({"name": "正文", "start": start, "height": y - start, "blocks": len(detail.blocks)})
        return self._write(image, lines=lines, resources=resources, sections=sections)


__all__ = ["NoticesRenderer", "RenderedNoticesImage"]
