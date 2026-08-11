"""玩家角色概览和详情图片渲染。

渲染器接收 typed snapshot，遍历全部合法列表项并生成运行期 PNG。为了让图像
回归可以检查动态布局和资源语义，PNG 额外带有 ``dnaby.text``、
``dnaby.layout``、``dnaby.resources`` 三个非敏感文本块；这些元数据不改变
AstrBot 的图片消息类型。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps
from PIL.PngImagePlugin import PngInfo

from ...modules.player.contracts import (
    AttributeBag,
    DamageCalculation,
    RoleDetail,
    RoleItem,
    RoleOverview,
    WeaponDetail,
    WeaponItem,
)

_FONT_PATH = Path(__file__).resolve().parents[3] / "dnaby" / "utils" / "fonts" / "dna_fonts.ttf"


@dataclass(slots=True)
class ResourceMap:
    """测试和部署可注入的图片资源映射。

    key 可以是 API 资源 URI，也可以是 renderer 约定的 ``kind:key``。没有资源
    时返回 ``None``，由 renderer 绘制带有明确 metadata 的 placeholder。
    """

    images: dict[str, Image.Image | Path] = field(default_factory=dict)
    original_panels: dict[str, Path] = field(default_factory=dict)

    def load(self, kind: str, key: str, source: str | None) -> Image.Image | None:
        """读取一个已注入的资源副本，不在渲染层发起网络请求。"""

        candidates = (source or "", f"{kind}:{key}", key)
        resource: Image.Image | Path | None = next(
            (self.images[candidate] for candidate in candidates if candidate in self.images),
            None,
        )
        if resource is None:
            return None
        if isinstance(resource, Image.Image):
            return resource.convert("RGBA").copy()
        with Image.open(resource) as image:
            return image.convert("RGBA")

    def original_panel(self, char_id: int) -> Path | None:
        """返回一个已存在的自定义角色面板原图。"""

        path = self.original_panels.get(str(char_id))
        return path if path is not None and path.is_file() else None


@dataclass(frozen=True, slots=True)
class RenderedPlayerImage:
    """渲染结果及供服务层登记原图的非框架信息。"""

    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]
    original_image_path: Path | None = None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if _FONT_PATH.is_file():
        return ImageFont.truetype(str(_FONT_PATH), size=size)
    return ImageFont.load_default()


def _text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _attribute_lines(attribute: AttributeBag) -> list[str]:
    """按服务端字段遍历属性袋，包含 extra 字段而非只显示固定白名单。"""

    lines: list[str] = []
    for key, value in attribute.model_dump(by_alias=True).items():
        if value is None or key == "empty":
            continue
        if isinstance(value, dict):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        else:
            lines.append(f"{key}: {_text_value(value)}")
    return lines


class PlayerRenderer:
    """生成角色概览和详情 PNG 的纯渲染服务。"""

    def __init__(self, output_dir: str | Path, resources: ResourceMap | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources or ResourceMap()

    def _new_image(self, width: int, height: int, color: tuple[int, int, int, int]) -> Image.Image:
        return Image.new("RGBA", (width, height), color)

    def _resource_image(
        self,
        image: Image.Image,
        resources: list[dict[str, str]],
        *,
        kind: str,
        key: str,
        source: str | None,
        box: tuple[int, int, int, int],
    ) -> None:
        loaded = self.resources.load(kind, key, source)
        status = "provided" if loaded is not None else "placeholder"
        resources.append(
            {
                "kind": kind,
                "key": key,
                "status": status,
                "source": source or "",
            },
        )
        x, y, width, height = box
        if loaded is None:
            color = {
                "role_avatar": (84, 107, 139, 255),
                "weapon_icon": (120, 91, 67, 255),
                "skill_icon": (115, 84, 126, 255),
                "mode_icon": (67, 121, 105, 255),
                "role_paint": (49, 61, 85, 255),
            }.get(kind, (80, 80, 80, 255))
            loaded = Image.new("RGBA", (width, height), color)
        fitted = ImageOps.contain(loaded, (width, height))
        paste_x = x + (width - fitted.width) // 2
        paste_y = y + (height - fitted.height) // 2
        image.alpha_composite(fitted, (paste_x, paste_y))

    @staticmethod
    def _draw_section_title(draw: ImageDraw.ImageDraw, y: int, title: str) -> None:
        draw.rounded_rectangle((30, y, 970, y + 52), radius=12, fill=(64, 79, 113, 255))
        draw.text((52, y + 26), title, fill=(250, 250, 250, 255), font=_font(26), anchor="lm")

    def render_overview(
        self,
        overview: RoleOverview,
        *,
        uid: str,
        uid_hidden: bool,
        show_unowned: bool = True,
    ) -> RenderedPlayerImage:
        """渲染完整总览，不在数据层截断角色或武器。"""

        sections_data: list[tuple[str, list[RoleItem | WeaponItem], str]] = [
            ("角色信息", list(overview.role_chars), "role_avatar"),
            ("近战武器", list(overview.close_weapons), "weapon_icon"),
            ("远程武器", list(overview.ranged_weapons), "weapon_icon"),
        ]
        filtered_sections = [
            (
                name,
                items if show_unowned else [item for item in items if item.unlocked],
                kind,
            )
            for name, items, kind in sections_data
        ]
        lines = [
            overview.role_name,
            f"UID {'***' if uid_hidden else uid}",
            f"等级: {_text_value(overview.level)}",
            f"总成就数: {overview.achievement_total}",
        ]
        lines.extend(f"{item.param_key}: {item.param_value}" for item in overview.params)
        for name, items, _kind in filtered_sections:
            lines.append(name)
            lines.extend(
                f"{item.name} | Lv.{item.level if item.level > 0 else '未解锁'}"
                for item in items
            )

        height = 190
        for _name, items, _kind in filtered_sections:
            rows = max(1, (len(items) + 4) // 5)
            height += 72 + rows * 120
        height += 48
        image = self._new_image(1200, height, (25, 31, 48, 255))
        draw = ImageDraw.Draw(image)
        draw.text((40, 42), "二重螺旋 · 角色总览", fill=(255, 215, 145, 255), font=_font(34))
        draw.text((40, 92), overview.role_name, fill=(255, 255, 255, 255), font=_font(30))
        draw.text(
            (40, 135),
            f"UID {'***' if uid_hidden else uid}    Lv.{_text_value(overview.level)}    总成就数 {overview.achievement_total}",
            fill=(210, 220, 232, 255),
            font=_font(20),
        )
        draw.text(
            (800, 42),
            " | ".join(f"{item.param_key}: {item.param_value}" for item in overview.params),
            fill=(214, 199, 145, 255),
            font=_font(16),
            anchor="ra",
        )

        resource_records: list[dict[str, str]] = []
        section_records: list[dict[str, Any]] = []
        y = 175
        for name, items, kind in filtered_sections:
            self._draw_section_title(draw, y, name)
            section_start = y
            y += 66
            rows = max(1, (len(items) + 4) // 5)
            for index, item in enumerate(items):
                x = 30 + (index % 5) * 235
                item_y = y + (index // 5) * 120
                item_key = str(item.char_id if isinstance(item, RoleItem) else item.weapon_id)
                source = item.icon
                self._resource_image(
                    image,
                    resource_records,
                    kind=kind,
                    key=item_key,
                    source=source,
                    box=(x, item_y, 78, 78),
                )
                unlocked = item.unlocked
                draw.text(
                    (x + 88, item_y + 20),
                    item.name,
                    fill=(255, 255, 255, 255) if unlocked else (144, 151, 166, 255),
                    font=_font(19),
                )
                level = item.level if item.level > 0 else "未解锁"
                draw.text(
                    (x + 88, item_y + 54),
                    f"Lv.{level}",
                    fill=(220, 205, 155, 255),
                    font=_font(17),
                )
            section_height = 66 + rows * 120
            section_records.append(
                {"name": name, "start": section_start, "height": section_height, "items": len(items)},
            )
            y += rows * 120

        return self._write(
            image,
            lines=lines,
            resources=resource_records,
            sections=section_records,
        )

    def render_detail(
        self,
        role_detail: RoleDetail,
        weapon_sections: list[tuple[str, WeaponDetail]],
        damage: DamageCalculation,
        *,
        uid: str,
        uid_hidden: bool,
    ) -> RenderedPlayerImage:
        """渲染动态高度详情图，完整遍历详情和伤害数据。"""

        lines: list[str] = [
            role_detail.char_name,
            f"UID {'***' if uid_hidden else uid}",
            f"Lv.{role_detail.level}",
            f"元素: {role_detail.element_name}",
            f"溯源等级: {role_detail.grade_level}",
        ]
        section_lines: list[tuple[str, list[str]]] = []
        section_lines.append(("角色头部", lines.copy()))

        attributes = [
            f"{key}: {_text_value(value)}"
            for key, value in role_detail.attribute.model_dump(by_alias=True).items()
            if value not in (None, [], "")
        ]
        section_lines.append(("角色属性", attributes))
        lines.extend(attributes)

        skill_lines = [
            f"{skill.skill_name} | Lv.{skill.level} | skillId={skill.skill_id}"
            for skill in role_detail.skills
        ]
        section_lines.append(("技能", skill_lines))
        lines.extend(skill_lines)

        trace_lines = [trace.description for trace in role_detail.traces]
        section_lines.append(("溯源", trace_lines))
        lines.extend(trace_lines)

        weapon_lines: list[str] = []
        for label, weapon in weapon_sections:
            weapon_lines.append(f"{label}: {weapon.name} | Lv.{weapon.level} | 精炼 {weapon.skill_level}")
            weapon_lines.extend(
                f"{label}.{key}: {_text_value(value)}"
                for key, value in weapon.attribute.model_dump(by_alias=True).items()
                if value not in (None, "")
            )
            weapon_lines.extend(
                f"{label}.魔之楔: {mode.name or '未佩戴'} +{mode.level or 0}"
                for mode in weapon.modes
            )
        section_lines.append(("武器", weapon_lines))
        lines.extend(weapon_lines)

        mode_lines = [
            f"魔之楔{index + 1}: {mode.name or '未佩戴'} +{mode.level or 0} (id={mode.id})"
            for index, mode in enumerate(role_detail.modes)
        ]
        section_lines.append(("魔之楔", mode_lines))
        lines.extend(mode_lines)

        damage_lines: list[str] = []
        if damage.data is None:
            damage_lines.append(f"伤害计算: {damage.message}")
        else:
            for skill in damage.data.skills:
                damage_lines.append(f"伤害技能: {skill.name} (id={skill.id})")
                for attribute in (*skill.normal_skill_attributes, *skill.damage_skill_attributes):
                    environment = (
                        f" / 环境值={_text_value(attribute.environment_value)}"
                        if attribute.environment_value is not None
                        else ""
                    )
                    damage_lines.append(
                        f"{skill.name}.{attribute.key}: {_text_value(attribute.value)}{environment}",
                    )
            for key, value in damage.data.damage.model_dump(by_alias=True).items():
                if value is not None:
                    damage_lines.append(f"伤害.{key}: {_text_value(value)}")
            damage_lines.extend(f"最终属性.{line}" for line in _attribute_lines(damage.data.final_attribute))
            damage_lines.extend(f"基础属性.{line}" for line in _attribute_lines(damage.data.base_attribute))
        section_lines.append(("伤害", damage_lines))
        lines.extend(damage_lines)

        section_records: list[dict[str, Any]] = []
        section_heights = [max(78, 60 + len(section) * 48) for _name, section in section_lines]
        height = 30 + sum(section_heights) + 40
        image = self._new_image(1000, height, (24, 30, 46, 255))
        draw = ImageDraw.Draw(image)
        resource_records: list[dict[str, str]] = []
        y = 20
        for index, ((name, section), section_height) in enumerate(zip(section_lines, section_heights)):
            self._draw_section_title(draw, y, name)
            section_start = y
            y += 62
            for line_index, line in enumerate(section):
                draw.text(
                    (45, y + line_index * 48),
                    line,
                    fill=(238, 240, 246, 255),
                    font=_font(19),
                )
            if index == 0:
                self._resource_image(
                    image,
                    resource_records,
                    kind="role_paint",
                    key=str(role_detail.char_id),
                    source=role_detail.paint,
                    box=(735, section_start + 66, 210, max(50, section_height - 80)),
                )
            elif name == "技能":
                for skill_index, skill in enumerate(role_detail.skills):
                    self._resource_image(
                        image,
                        resource_records,
                        kind="skill_icon",
                        key=str(skill.skill_id),
                        source=skill.icon,
                        box=(750, y - 45 + skill_index * 48, 35, 35),
                    )
            elif name == "武器":
                for weapon_index, (_label, weapon) in enumerate(weapon_sections):
                    self._resource_image(
                        image,
                        resource_records,
                        kind="weapon_icon",
                        key=str(weapon.weapon_id),
                        source=weapon.icon,
                        box=(750, y - 45 + weapon_index * 48, 35, 35),
                    )
            elif name == "魔之楔":
                for mode_index, mode in enumerate(role_detail.modes):
                    self._resource_image(
                        image,
                        resource_records,
                        kind="mode_icon",
                        key=str(mode.id),
                        source=mode.icon,
                        box=(750, y - 45 + mode_index * 48, 35, 35),
                    )
            y = section_start + section_height
            section_records.append(
                {"name": name, "start": section_start, "height": section_height, "items": len(section)},
            )

        original_path = self.resources.original_panel(role_detail.char_id)
        if original_path is not None:
            resource_records.append(
                {
                    "kind": "original_panel",
                    "key": str(role_detail.char_id),
                    "status": "provided",
                    "source": "runtime-panel",
                },
            )
        else:
            resource_records.append(
                {
                    "kind": "original_panel",
                    "key": str(role_detail.char_id),
                    "status": "missing",
                    "source": "runtime-panel",
                },
            )
        return self._write(
            image,
            lines=lines,
            resources=resource_records,
            sections=section_records,
            original_image_path=original_path,
        )

    def _write(
        self,
        image: Image.Image,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
        original_image_path: Path | None = None,
    ) -> RenderedPlayerImage:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"player-{uuid.uuid4().hex}.png"
        metadata = PngInfo()
        metadata.add_text("dnaby.text", "\n".join(lines))
        metadata.add_text(
            "dnaby.layout",
            json.dumps({"width": image.width, "height": image.height, "sections": sections}, ensure_ascii=False),
        )
        metadata.add_text(
            "dnaby.resources",
            json.dumps(resources, ensure_ascii=False),
        )
        image.save(path, format="PNG", pnginfo=metadata)
        return RenderedPlayerImage(
            path=path,
            width=image.width,
            height=image.height,
            text_lines=tuple(lines),
            resources=tuple(resources),
            sections=tuple(sections),
            original_image_path=original_image_path,
        )


__all__ = ["PlayerRenderer", "RenderedPlayerImage", "ResourceMap"]
