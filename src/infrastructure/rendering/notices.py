"""密函与公告的确定性 Pillow 渲染器。

渲染器只消费 typed notices 快照与运行期资源索引。画布高度按完整数据动态计算，
PNG 元数据保存完整文本、布局段和素材状态，便于不依赖像素 hash 的行为回归审查。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
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

    async def render_mh(self, snapshot: MhSnapshot) -> RenderedNoticesImage:
        """复用 legacy 默认简洁密函绘制核心。"""

        from dnaby.dna_mh.draw_mh import draw_mh_simple
        from dnaby.utils import get_datetime
        from dnaby.utils.api.model import DNARoleForToolInstanceInfo

        legacy = [
            DNARoleForToolInstanceInfo.model_validate(
                {
                    "mh_type": section.mh_type,
                    "instances": [
                        {"id": item.instance_id, "name": item.name}
                        for item in section.instances
                    ],
                },
            )
            for section in snapshot.sections
        ]
        now = get_datetime()
        next_refresh = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        image_bytes = await draw_mh_simple(
            legacy,
            int((next_refresh - now).total_seconds()),
        )
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGBA")

        lines = ["二重螺旋 · 密函"]
        for section in snapshot.sections:
            lines.append(f"{section.type_name}:")
            lines.extend(f"{item.name} (id={item.instance_id})" for item in section.instances)
        resources: list[dict[str, str]] = [self._font_resource()]
        sections: list[dict[str, Any]] = []
        for section in snapshot.sections:
            sections.append(
                {
                    "name": section.type_name,
                    "items": len(section.instances),
                },
            )
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def render_ann_list(self, snapshot: AnnSnapshot) -> RenderedNoticesImage:
        """渲染公告列表，按序号展示全部公告标题与时间。"""

        from dnaby.dna_ann.ann_card import draw_ann_list_img

        payload = [
            {"postId": post.post_id, "postTitle": post.title, "postTime": post.time, "postCover": post.preview}
            for post in snapshot.posts
        ]
        image_bytes = await draw_ann_list_img(payload)
        if not isinstance(image_bytes, bytes):
            raise TypeError("公告列表 legacy 绘制失败")
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGBA")

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
        sections: list[dict[str, Any]] = []
        sections.append({"name": "公告", "items": len(snapshot.posts)})
        return self._write(image, lines=lines, resources=resources, sections=sections)

    async def render_ann_detail(self, detail: AnnDetail) -> RenderedNoticesImage:
        """复用 legacy 公告详情布局，保留中文字体、正文图片与分页。"""

        from dnaby.dna_ann.ann_card import draw_ann_detail_card

        lines = ["二重螺旋 · 公告详情", detail.title]
        resources: list[dict[str, str]] = [self._font_resource()]
        text_lines: list[str] = []
        blocks: list[tuple[str, str]] = []
        for index, block in enumerate(detail.blocks):
            if block.kind == "text":
                text_lines.append(block.text)
                blocks.append(("text", block.text))
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
            blocks.append(("image", block.image_url))
        lines.extend(text_lines)
        rendered = await draw_ann_detail_card(detail.post_id, detail.title, blocks)
        image_bytes = rendered[0] if isinstance(rendered, list) else rendered
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGBA")
        sections = [{"name": "正文", "blocks": len(detail.blocks)}]
        return self._write(image, lines=lines, resources=resources, sections=sections)


__all__ = ["NoticesRenderer", "RenderedNoticesImage"]
