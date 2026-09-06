"""角色总览与详情卡片的 HTML/T2I 与确定性渲染器。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageFont, ImageOps
from pydantic import BaseModel

from ...entry.event import EventActor
from ...modules.player.contracts import (
    DamageCalculation,
    RoleDetail,
    RoleOverview,
    WeaponDetail,
)
from ...modules.player.damage_service import (
    RoleDamageBuild,
)
from ...utils import dna_api
from ...utils.api.damage_model import CharacterCalculateData
from ...utils.api.model import (
    DNAWeaponDetailRes,
    Mode,
    RoleShowForTool,
)
from ...utils.api.model import (
    WeaponDetail as LegacyWeaponDetail,
)
from ...utils.api.request_util import DNAApiResp
from ...utils.database.models import DNAUser
from ...utils.image import (
    get_attr_img,
    get_avatar_img,
    get_grade_img,
    get_mod_img,
    get_paint_img,
    get_skill_img,
    get_weapon_attr_img,
    get_weapon_img,
)
from ...utils.session import EventContext
from ..resources.encyclopedia import EncyclopediaResourceStore
from .artifact import RenderedArtifact
from .artifact_store import write_rendered_artifact
from .assets import font_data_uri, image_data_uri, pil_image_data_uri
from .image_inspector import inspect_image
from .damage_renderer import draw_role_damage_section
from .fonts import load_runtime_font
from .payloads import build_profile_header
from .renderer import HtmlRenderer
from .spec import RenderSpec
from .weapon_renderer import draw_weapon_detail_section

_RENDERER = HtmlRenderer()
RESOURCES_DIR = Path(__file__).parents[2] / "resources"
COMMON_PATH = RESOURCES_DIR / "textures" / "common"
DETAIL_TEXT_PATH = RESOURCES_DIR / "textures" / "detail"
ROLE_TEXT_PATH = RESOURCES_DIR / "textures" / "role"
FONT_ORIGIN_PATH = RESOURCES_DIR / "fonts" / "dna_fonts.ttf"


# ---------------------------------------------------------------------------
# 1. 角色总览卡 (Role Overview)
# ---------------------------------------------------------------------------


class ItemTemp(BaseModel):
    type: Literal["role", "weapon"]
    id: int
    name: str
    level: int
    element_icon: str
    icon: str
    grade_level: int | None = None
    unlocked: bool = False


async def _item_payload(item: ItemTemp) -> dict[str, object]:
    if item.type == "role":
        image = await get_avatar_img(item.id, item.icon)
        element = await get_attr_img(pic_url=item.element_icon)
    else:
        image = await get_weapon_img(item.id, item.icon)
        element = await get_weapon_attr_img(pic_url=item.element_icon)

    # 仅当条目已解锁且命座等级大于 0 时才显示命座徽章，0 命或未解锁不渲染徽章
    grade_level = item.grade_level
    grade_uri = (
        pil_image_data_uri(get_grade_img(grade_level))
        if item.unlocked and grade_level is not None and grade_level > 0
        else None
    )

    return {
        "element": pil_image_data_uri(
            element.resize((element.width // 2, element.height // 2))
        ),
        "grade": grade_uri,
        "image": pil_image_data_uri(image),
        "level": item.level,
        "name": item.name,
        "type": item.type,
        "unlocked": item.unlocked,
    }


async def _section_payload(
    items: list[ItemTemp],
    title: str,
    show_none: bool,
    background_path: Path,
) -> dict[str, object]:
    visible = items if show_none else [item for item in items if item.unlocked]
    return {
        "background": image_data_uri(background_path),
        "items": list(await asyncio.gather(*(_item_payload(item) for item in visible))),
        "title": title,
    }


async def _draw_role_overview_card(
    ctx: EventContext,
    role_show: RoleShowForTool,
    show_none: bool = True,
    uid_hidden: bool = False,
) -> bytes:
    role_items = [
        ItemTemp(
            type="role",
            id=getattr(role, "charId", getattr(role, "char_id", 0)),
            name=getattr(role, "name", ""),
            level=getattr(role, "level", 0),
            element_icon=getattr(
                role, "elementIcon", getattr(role, "element_icon", "")
            ),
            icon=getattr(role, "icon", ""),
            grade_level=getattr(role, "gradeLevel", getattr(role, "grade_level", None)),
            unlocked=getattr(role, "unLocked", getattr(role, "unlocked", False)),
        )
        for role in role_show.roleChars
    ]
    close_items = [
        ItemTemp(
            type="weapon",
            id=getattr(weapon, "weaponId", getattr(weapon, "weapon_id", 0)),
            name=getattr(weapon, "name", ""),
            level=getattr(weapon, "level", 0),
            element_icon=getattr(
                weapon, "elementIcon", getattr(weapon, "element_icon", "")
            ),
            icon=getattr(weapon, "icon", ""),
            grade_level=getattr(
                weapon, "skillLevel", getattr(weapon, "skill_level", None)
            ),
            unlocked=getattr(weapon, "unLocked", getattr(weapon, "unlocked", False)),
        )
        for weapon in role_show.closeWeapons
    ]
    lang_items = [
        ItemTemp(
            type="weapon",
            id=getattr(weapon, "weaponId", getattr(weapon, "weapon_id", 0)),
            name=getattr(weapon, "name", ""),
            level=getattr(weapon, "level", 0),
            element_icon=getattr(
                weapon, "elementIcon", getattr(weapon, "element_icon", "")
            ),
            icon=getattr(weapon, "icon", ""),
            grade_level=getattr(
                weapon, "skillLevel", getattr(weapon, "skill_level", None)
            ),
            unlocked=getattr(weapon, "unLocked", getattr(weapon, "unlocked", False)),
        )
        for weapon in role_show.langRangeWeapons
    ]
    achievements = [
        {"label": "角色数量", "value": str(sum(item.unlocked for item in role_items))},
        {"label": "近战武器", "value": str(sum(item.unlocked for item in close_items))},
        {"label": "远程武器", "value": str(sum(item.unlocked for item in lang_items))},
    ]
    achievements.extend(
        {
            "label": getattr(item, "paramKey", getattr(item, "param_key", "")),
            "value": str(getattr(item, "paramValue", getattr(item, "param_value", ""))),
        }
        for item in role_show.params
        if getattr(item, "paramKey", getattr(item, "param_key", ""))
        in ("装饰数量", "魔灵数量")
    )
    total_achv = getattr(
        role_show.roleAchv, "total", getattr(role_show, "achievement_total", 0)
    )
    achievements.append({"label": "总成就数", "value": str(total_achv)})
    header_stats = [
        (
            getattr(item, "paramKey", getattr(item, "param_key", "")),
            str(getattr(item, "paramValue", getattr(item, "param_value", ""))),
        )
        for item in role_show.params
        if getattr(item, "paramKey", getattr(item, "param_key", ""))
        in ("总活跃天数", "游戏时长")
    ]
    header = await build_profile_header(
        ctx,
        getattr(role_show, "roleId", getattr(role_show, "role_id", "")),
        getattr(role_show, "roleName", getattr(role_show, "role_name", "")),
        user_level=role_show.level,
        stats=header_stats,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )

    sections = [
        await _section_payload(
            role_items, "角色信息", show_none, ROLE_TEXT_PATH / "bg" / "bg1.png"
        ),
        await _section_payload(
            close_items, "近战武器", show_none, ROLE_TEXT_PATH / "bg" / "bg5.png"
        ),
        await _section_payload(
            lang_items, "远程武器", show_none, ROLE_TEXT_PATH / "bg" / "bg4.png"
        ),
    ]
    section_counts = [
        len(items) if show_none else sum(item.unlocked for item in items)
        for items in (role_items, close_items, lang_items)
    ]
    height = 800 + sum(
        70 + 320 * math.ceil(count / 5) for count in section_counts if count
    )

    return await _RENDERER.render(
        "cards/role_info.html.j2",
        {
            "achievements": achievements,
            "background": image_data_uri(COMMON_PATH / "bg1.jpg"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "header": header,
            "header_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "info_bar": image_data_uri(ROLE_TEXT_PATH / "info_bar.png"),
            "div_background": image_data_uri(ROLE_TEXT_PATH / "div_bg.png"),
            "item_foreground": image_data_uri(ROLE_TEXT_PATH / "item_fg.png"),
            "item_mask": image_data_uri(ROLE_TEXT_PATH / "item_mask.png"),
            "sections": sections,
            "title_background": image_data_uri(ROLE_TEXT_PATH / "title_bg.jpg"),
            "title_mask": image_data_uri(ROLE_TEXT_PATH / "title_mask.png"),
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )


draw_role_overview_card = _draw_role_overview_card


async def draw_role_info_card_core(
    role_show: RoleShowForTool,
    uid_hidden: bool = False,
    show_none: bool = True,
    ev_stub: EventContext | None = None,
    avatar_user_id: str | None = None,
) -> bytes:
    ctx = ev_stub or EventContext(user_id=avatar_user_id or "0")
    return await _draw_role_overview_card(
        ctx, role_show, show_none=show_none, uid_hidden=uid_hidden
    )


# ---------------------------------------------------------------------------
# 2. 角色详情卡 (Role Detail)
# ---------------------------------------------------------------------------

ATTR_SPECS = (
    ("atk", "atk", "攻击", "icon1.png"),
    ("maxHp", "max_hp", "生命", "icon10.png"),
    ("maxES", "max_es", "护盾", "icon11.png"),
    ("defense", "defense", "防御", "icon9.png"),
    ("maxSp", "max_sp", "最大神志", "icon8.png"),
    ("skillIntensity", "skill_intensity", "技能威力", "icon7.png"),
    ("skillRange", "skill_range", "技能范围", "icon6.png"),
    ("skillSustain", "skill_sustain", "技能耐久", "icon5.png"),
    ("skillEfficiency", "skill_efficiency", "技能效益", "icon4.png"),
    ("strongValue", "strong_value", "昂扬", "icon3.png"),
    ("enmityValue", "enmity_value", "背水", "icon2.png"),
)


async def _load_weapon_detail(
    dna_user: DNAUser,
    weapon_id: int,
    weapon_eid: str,
) -> LegacyWeaponDetail | None:
    response = await dna_api.get_weapon_detail(dna_user, weapon_id, weapon_eid)
    if not response.is_success:
        return None
    if response.data is None:
        raise RuntimeError(f"武器详情成功响应缺少 data: weapon_id={weapon_id}")
    return DNAWeaponDetailRes.model_validate(response.data).weaponDetail


def _format_attribute(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value or "")


def _get_attr_val(attr: Any, camel: str, snake: str) -> Any:
    if attr is None:
        return ""
    val = getattr(attr, camel, None)
    if val is not None:
        return val
    val = getattr(attr, snake, None)
    if val is not None:
        return val
    return getattr(attr, camel.lower(), "")


def _attribute_payload(role_detail: Any) -> list[dict[str, str]]:
    attr = getattr(role_detail, "attribute", None)
    return [
        {
            "background": image_data_uri(
                DETAIL_TEXT_PATH / f"prop_info_bar{1 if index % 2 == 0 else 2}.png"
            ),
            "icon": image_data_uri(DETAIL_TEXT_PATH / "icons" / icon_name),
            "label": label,
            "value": _format_attribute(_get_attr_val(attr, camel, snake)),
        }
        for index, (camel, snake, label, icon_name) in enumerate(ATTR_SPECS)
    ]


async def _skill_payload(role_detail: Any) -> list[dict[str, object]]:
    char_id = getattr(role_detail, "charId", getattr(role_detail, "char_id", 0))
    skills = getattr(role_detail, "skills", [])
    return [
        {
            "icon": pil_image_data_uri(
                await get_skill_img(
                    char_id,
                    getattr(skill, "skillName", getattr(skill, "skill_name", "")),
                    getattr(skill, "icon", ""),
                )
            ),
            "level": skill.level,
            "name": getattr(skill, "skillName", getattr(skill, "skill_name", "")),
        }
        for skill in skills[:3]
    ]


async def _mode_payload(mode: Any, position: str) -> dict[str, object]:
    quality = getattr(mode, "quality", None) or 1
    payload: dict[str, object] = {
        "background": image_data_uri(
            DETAIL_TEXT_PATH / f"mod/mod_{position}_{quality}.png"
        ),
        "icon": None,
        "level": None,
        "name": getattr(mode, "name", "") or "",
        "position": position,
    }
    mode_id = getattr(mode, "id", -1)
    if mode_id != -1:
        payload["icon"] = pil_image_data_uri(
            await get_mod_img(mode_id, getattr(mode, "icon", ""))
        )
        level = getattr(mode, "level", 0)
        payload["level"] = f"+{level}" if level else None
    return payload


async def _role_modes_payload(modes: list[Any]) -> list[dict[str, object]]:
    padded = list(modes) + [Mode(id=-1) for _ in range(max(0, 9 - len(modes)))]
    order = tuple((index, "left") for index in (0, 2, 4, 6)) + tuple(
        (index, "right") for index in (1, 3, 7, 5)
    )
    payload = [
        await _mode_payload(padded[index], position) for index, position in order
    ]
    payload.append(await _mode_payload(padded[8], "center"))
    return payload


async def _hero_payload(
    char_id: str,
    role_detail: Any,
    custom_panel: Path | None = None,
) -> tuple[Path | None, dict[str, str]]:
    role_panel = None
    if custom_panel is not None and custom_panel.is_file():
        role_panel = (custom_panel, Image.open(custom_panel))

    if role_panel is not None:
        original_path, image = role_panel
        panel_size = (1000, 850)
        if image.width >= image.height:
            panel = ImageOps.fit(
                image.convert("RGBA"), panel_size, method=Image.Resampling.LANCZOS
            )
        else:
            portrait_size = (600, 850)
            portrait = ImageOps.fit(
                image.convert("RGBA"), portrait_size, method=Image.Resampling.LANCZOS
            )
            side_mask = Image.new("L", portrait_size, 255)
            side_fade = (
                Image.linear_gradient("L")
                .rotate(270, expand=True)
                .resize((72, portrait_size[1]))
            )
            side_mask.paste(side_fade, (portrait_size[0] - 72, 0))
            panel = Image.new("RGBA", panel_size)
            panel.alpha_composite(
                Image.composite(portrait, Image.new("RGBA", portrait_size), side_mask)
            )
        bottom_mask = Image.new("L", panel_size, 255)
        bottom_fade = ImageOps.invert(Image.linear_gradient("L")).resize(
            (panel_size[0], 72)
        )
        bottom_mask.paste(bottom_fade, (0, panel_size[1] - 72))
        panel = Image.composite(panel, Image.new("RGBA", panel_size), bottom_mask)
        return original_path, {"image": pil_image_data_uri(panel), "kind": "panel"}

    image = await get_paint_img(char_id, getattr(role_detail, "paint", ""))
    paint = image.convert("RGBA").resize((1056, 1056), Image.Resampling.LANCZOS)
    panel = Image.new("RGBA", (1000, 850))
    panel.alpha_composite(paint, (-280, -100))
    return None, {"image": pil_image_data_uri(panel), "kind": "paint"}


async def _draw_role_detail_card(
    ctx: EventContext,
    char_id: str,
    char_name: str,
    role_show: RoleShowForTool,
    role_detail: Any,
    con_weapon: Any = None,
    close_weapon: Any = None,
    ranged_weapon: Any = None,
    damage_calc_response: DNAApiResp[CharacterCalculateData] | None = None,
    uid_hidden: bool = False,
    custom_panel: Path | None = None,
) -> tuple[bytes, Path | None]:
    damage = None
    if damage_calc_response is not None:
        damage_build = RoleDamageBuild(
            role_detail=role_detail,
            con_weapon_detail=con_weapon,
            close_weapon_detail=close_weapon,
            lang_range_weapon_detail=ranged_weapon,
        )
        damage = draw_role_damage_section(
            damage_build,
            damage_calc_response,
        )
    weapon_sections = []
    for title, weapon in (
        ("同律武器", con_weapon),
        ("近战武器", close_weapon),
        ("远程武器", ranged_weapon),
    ):
        if weapon is not None:
            weapon_sections.append(await draw_weapon_detail_section(weapon, title))

    original_path, hero = await _hero_payload(
        char_id, role_detail, custom_panel=custom_panel
    )
    header = await build_profile_header(
        ctx,
        getattr(role_show, "roleId", getattr(role_show, "role_id", "")),
        getattr(role_show, "roleName", getattr(role_show, "role_name", "")),
        user_level=role_show.level,
        stats=[
            (
                getattr(item, "paramKey", getattr(item, "param_key", "")),
                str(getattr(item, "paramValue", getattr(item, "param_value", ""))),
            )
            for item in role_show.params
            if getattr(item, "paramKey", getattr(item, "param_key", ""))
            in ("总活跃天数", "游戏时长")
        ],
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    grade_level = getattr(
        role_detail, "gradeLevel", getattr(role_detail, "grade_level", 0)
    )
    grade_total = 7 if grade_level >= 7 else 6
    grades = [
        {
            "background": image_data_uri(
                DETAIL_TEXT_PATH
                / ("grade_1.png" if index <= grade_level else "grade_0.png")
            ),
            "icon": pil_image_data_uri(get_grade_img(index)),
            "index": index,
            "left": 50 + (index - 1) * (375 // (grade_total - 1)),
            "unlocked": index <= grade_level,
        }
        for index in range(1, grade_total + 1)
    ]
    card = await _RENDERER.render(
        "cards/role_detail.html.j2",
        {
            "attributes": _attribute_payload(role_detail),
            "background": image_data_uri(COMMON_PATH / "bg2.jpg"),
            "divider": image_data_uri(COMMON_PATH / "div.png"),
            "damage": damage,
            "element_icon": pil_image_data_uri(
                await get_attr_img(
                    char_id,
                    getattr(
                        role_detail,
                        "elementIcon",
                        getattr(role_detail, "element_icon", ""),
                    ),
                )
            ),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_image": image_data_uri(COMMON_PATH / "footer.png"),
            "grades": grades,
            "header": header,
            "hero": hero,
            "point": image_data_uri(DETAIL_TEXT_PATH / "point.png"),
            "profile_background": image_data_uri(COMMON_PATH / "avatar_title_bg.png"),
            "role": {
                "grade": grade_level,
                "grade_icon": pil_image_data_uri(get_grade_img(grade_level))
                if grade_level > 0
                else None,
                "level": role_detail.level,
                "name": char_name,
            },
            "role_modes": await _role_modes_payload(getattr(role_detail, "modes", [])),
            "skills": await _skill_payload(role_detail),
            "skill_background": image_data_uri(DETAIL_TEXT_PATH / "skill_bg.png"),
            "weapon_sections": weapon_sections,
            "width": 1000,
        },
        RenderSpec(width=1000, full_page=True, image_format="jpeg"),
    )
    return card, original_path


draw_role_detail_card = _draw_role_detail_card


async def render_role_card_image(
    role_detail: Any,
    weapons: list[tuple[str, Any]],
    damage_data: CharacterCalculateData | None,
    *,
    uid: str,
    uid_hidden: bool,
    avatar_title: Image.Image | None = None,
    damage_message: str | None = None,
) -> Image.Image:
    con_weapon = next((w for label, w in weapons if "同律" in label), None)
    close_weapon = next((w for label, w in weapons if "近战" in label), None)
    ranged_weapon = next((w for label, w in weapons if "远程" in label), None)

    char_id = str(getattr(role_detail, "charId", getattr(role_detail, "char_id", 0)))
    char_name = getattr(role_detail, "charName", getattr(role_detail, "char_name", ""))
    role_show = RoleShowForTool.model_validate(
        {
            "roleId": char_id,
            "roleName": char_name,
            "level": role_detail.level,
            "params": [],
            "roleAchv": {"total": 0},
            "roleChars": [],
            "closeWeapons": [],
            "langRangeWeapons": [],
        }
    )
    ctx = EventContext(user_id=uid)
    damage_calc = (
        DNAApiResp.ok(damage_data)
        if damage_data is not None
        else DNAApiResp.err(damage_message)
        if damage_message is not None
        else None
    )
    card_bytes, _ = await _draw_role_detail_card(
        ctx,
        char_id,
        char_name,
        role_show,
        role_detail,
        con_weapon=con_weapon,
        close_weapon=close_weapon,
        ranged_weapon=ranged_weapon,
        damage_calc_response=damage_calc,
        uid_hidden=uid_hidden,
    )
    return Image.open(BytesIO(card_bytes)).convert("RGBA")


# ---------------------------------------------------------------------------
# 3. ResourceMap & PlayerRenderer Class
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceMap:
    """管理角色、武器与立绘资源路径。"""

    root: Path | None = None
    role_avatars: Mapping[str, Path] = field(default_factory=dict)
    role_paints: Mapping[str, Path] = field(default_factory=dict)
    original_panels: Mapping[str, Path] = field(default_factory=dict)
    fonts: Mapping[str, Path] = field(default_factory=dict)

    @classmethod
    def from_root(cls, root: str | Path) -> ResourceMap:
        root_path = Path(root).expanduser().resolve()
        return cls(root=root_path)

    @property
    def font_path(self) -> Path | None:
        if self.root is not None:
            font = self.root / "fonts" / "dna_fonts.ttf"
            if font.is_file():
                return font
        return self.fonts.get("dna_fonts")

    @property
    def font_status(self) -> str:
        return "provided" if self.font_path is not None else "placeholder"

    def get_font_status(self) -> str:
        return self.font_status

    def original_panel(self, char_id: str | int) -> Path | None:
        key = str(char_id)
        if key in self.original_panels:
            return self.original_panels[key]
        if self.root is not None:
            p = self.root / "panel" / f"{key}.png"
            if p.is_file():
                return p
        return None

    def role_avatar(self, char_id: str | int) -> Path | None:
        key = str(char_id)
        if key in self.role_avatars:
            return self.role_avatars[key]
        if self.root is not None:
            p = self.root / "images" / "role_avatar" / f"{key}.png"
            if p.is_file():
                return p
        return None

    def role_paint(self, char_id: str | int) -> Path | None:
        key = str(char_id)
        if key in self.role_paints:
            return self.role_paints[key]
        if self.root is not None:
            p = self.root / "images" / "role_paint" / f"{key}.png"
            if p.is_file():
                return p
        return None

    def get_avatar_status(self, char_id: str | int) -> str:
        return "provided" if self.role_avatar(char_id) is not None else "placeholder"

    def get_paint_status(self, char_id: str | int) -> str:
        return "provided" if self.role_paint(char_id) is not None else "placeholder"

    def get_panel_status(self, char_id: str | int) -> str:
        return "provided" if self.original_panel(char_id) is not None else "placeholder"

    def load(self, kind: str, key: str | int, fallback: Any = None) -> Any:
        path = None
        if kind == "role_avatar":
            path = self.role_avatar(key)
        elif kind == "role_paint":
            path = self.role_paint(key)
        elif kind in ("original_panel", "panel"):
            path = self.original_panel(key)
        if path is not None and path.is_file():
            try:
                return Image.open(path)
            except (OSError, ValueError):
                return path
        return fallback


def _text_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


@dataclass(frozen=True, slots=True)
class RenderedPlayerImage:
    path: Path
    width: int
    height: int
    text_lines: tuple[str, ...]
    resources: tuple[dict[str, str], ...]
    sections: tuple[dict[str, Any], ...]
    original_image_path: Path | None = None
    # 管理 API 会在读取 base64 后立即释放这类 renderer 生成的临时文件；
    # 非临时资源路径必须显式保持 False，避免被管理预览误删。
    temporary: bool = False
    # 缺少角色/面板等素材时可以发送本次占位图，但不能覆盖完整卡片缓存。
    incomplete: bool = False
    sidecar: Path | None = None
    manifest: Path | None = None
    media_type: str = "image/png"


class PlayerRenderer:
    """生成角色总览与详情卡片的运行期 T2I 图片。"""

    def __init__(
        self, output_dir: str | Path, resources: EncyclopediaResourceStore | ResourceMap
    ) -> None:
        self.output_dir = Path(output_dir)
        self.resources = resources

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_path = getattr(self.resources, "font_path", None)
        return load_runtime_font(font_path, size)

    def _font_resource(self) -> dict[str, str]:
        if isinstance(self.resources, ResourceMap):
            return {
                "kind": "font",
                "key": "dna_fonts",
                "status": self.resources.get_font_status(),
                "source": "fonts/dna_fonts.ttf",
            }
        return {
            "kind": "font",
            "key": "dna_fonts",
            "status": self.resources.font_status,
            "source": "fonts/dna_fonts.ttf"
            if self.resources.font_path is not None
            else "",
        }

    def _write(
        self,
        image_bytes: bytes,
        *,
        lines: list[str],
        resources: list[dict[str, str]],
        sections: list[dict[str, Any]],
        original_image_path: Path | None = None,
    ) -> RenderedPlayerImage:
        inspection = inspect_image(image_bytes, media_type="image/jpeg")
        artifact = RenderedArtifact.from_bytes(
            image_bytes,
            media_type="image/jpeg",
            metadata={
                "dnaby.text": "\n".join(lines),
                "dnaby.layout": {
                    "width": inspection.width,
                    "height": inspection.height,
                    "sections": sections,
                },
                "dnaby.resources": resources,
            },
        )
        response = write_rendered_artifact(self.output_dir, artifact, prefix="player-")
        return RenderedPlayerImage(
            path=Path(response.image),
            width=artifact.width,
            height=artifact.height,
            text_lines=tuple(lines),
            resources=tuple(resources),
            sections=tuple(sections),
            temporary=True,
            original_image_path=original_image_path,
            incomplete=any(
                resource.get("status") == "placeholder" for resource in resources
            ),
            sidecar=Path(response.sidecar) if response.sidecar is not None else None,
            manifest=Path(response.manifest) if response.manifest is not None else None,
            media_type=artifact.media_type,
        )

    async def render_overview(
        self,
        overview: RoleOverview,
        *,
        uid: str,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
        uid_hidden: bool = False,
        show_unowned: bool = True,
    ) -> RenderedPlayerImage:
        role_show = RoleShowForTool.model_validate(
            {
                "roleId": overview.role_id,
                "roleName": overview.role_name,
                "level": overview.level,
                "params": [item.model_dump(by_alias=True) for item in overview.params],
                "roleAchv": {"total": overview.achievement_total},
                "roleChars": [
                    item.model_dump(by_alias=True) for item in overview.role_chars
                ],
                "closeWeapons": [
                    item.model_dump(by_alias=True) for item in overview.close_weapons
                ],
                "langRangeWeapons": [
                    item.model_dump(by_alias=True) for item in overview.ranged_weapons
                ],
            }
        )
        ev_stub = (
            None
            if actor is None
            else EventContext(
                user_id=target_user_id or actor.user_id,
                bot_id=actor.bot_id,
                group_id=actor.group_id or "",
                at=target_user_id or actor.user_id,
                unified_msg_origin=actor.unified_msg_origin or "",
            )
        )
        image_bytes = await draw_role_info_card_core(
            role_show,
            uid_hidden=uid_hidden,
            show_none=show_unowned,
            ev_stub=ev_stub,
            avatar_user_id=target_user_id
            or (actor.user_id if actor is not None else uid),
        )
        lines = [
            overview.role_name,
            f"UID {'***' if uid_hidden else uid}",
            f"等级: {_text_value(overview.level)}",
        ]
        lines.extend(
            f"{item.param_key}: {item.param_value}" for item in overview.params
        )
        sections = [
            {"name": "角色信息", "items": len(overview.role_chars)},
            {"name": "近战武器", "items": len(overview.close_weapons)},
            {"name": "远程武器", "items": len(overview.ranged_weapons)},
        ]
        resources = [self._font_resource()]
        if isinstance(self.resources, ResourceMap):
            for role in overview.role_chars:
                if self.resources.root is not None:
                    status = self.resources.get_avatar_status(role.char_id)
                else:
                    status = "legacy_download"
                resources.append(
                    {
                        "kind": "role_avatar",
                        "key": str(role.char_id),
                        "status": status,
                        "source": f"images/role_avatar/{role.char_id}.png",
                    }
                )
            for weapon in list(overview.close_weapons) + list(overview.ranged_weapons):
                resources.append(
                    {
                        "kind": "weapon_icon",
                        "key": str(weapon.weapon_id),
                        "status": "legacy_download",
                        "source": f"images/weapon/{weapon.weapon_id}.png",
                    }
                )
        return self._write(
            image_bytes, lines=lines, resources=resources, sections=sections
        )

    async def render_overview_legacy(
        self,
        overview: RoleOverview,
        *,
        uid: str,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
        uid_hidden: bool = False,
        show_unowned: bool = True,
    ) -> RenderedPlayerImage:
        return await self.render_overview(
            overview,
            uid=uid,
            actor=actor,
            target_user_id=target_user_id,
            uid_hidden=uid_hidden,
            show_unowned=show_unowned,
        )

    async def render_detail(
        self,
        detail: RoleDetail,
        weapons: list[tuple[str, WeaponDetail]] | None = None,
        damage_calc: DamageCalculation | None = None,
        *,
        uid: str,
        uid_hidden: bool = False,
        damage_message: str | None = None,
        overview: RoleOverview | None = None,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
    ) -> RenderedPlayerImage:
        weapons = weapons or []
        damage_data = (
            None
            if damage_calc is None or damage_calc.data is None
            else CharacterCalculateData.model_validate(
                damage_calc.data.model_dump(by_alias=True),
            )
        )
        con_weapon = next((w for label, w in weapons if "同律" in label), None)
        close_weapon = next((w for label, w in weapons if "近战" in label), None)
        ranged_weapon = next((w for label, w in weapons if "远程" in label), None)

        char_id = str(detail.char_id)
        char_name = detail.char_name
        if overview is not None:
            role_show = RoleShowForTool.model_validate(
                {
                    "roleId": overview.role_id,
                    "roleName": overview.role_name,
                    "level": overview.level,
                    "params": [p.model_dump(by_alias=True) for p in overview.params],
                    "roleAchv": {"total": overview.achievement_total},
                    "roleChars": [
                        c.model_dump(by_alias=True) for c in overview.role_chars
                    ],
                    "closeWeapons": [
                        w.model_dump(by_alias=True) for w in overview.close_weapons
                    ],
                    "langRangeWeapons": [
                        w.model_dump(by_alias=True) for w in overview.ranged_weapons
                    ],
                }
            )
        else:
            role_show = RoleShowForTool.model_validate(
                {
                    "roleId": char_id,
                    "roleName": char_name,
                    "level": detail.level,
                    "params": [],
                    "roleAchv": {"total": 0},
                    "roleChars": [],
                    "closeWeapons": [],
                    "langRangeWeapons": [],
                }
            )

        ev_stub = (
            None
            if actor is None
            else EventContext(
                user_id=target_user_id or actor.user_id,
                bot_id=actor.bot_id,
                group_id=actor.group_id or "",
                at=target_user_id or actor.user_id,
                unified_msg_origin=actor.unified_msg_origin or "",
            )
        )
        ctx = ev_stub or EventContext(
            user_id=target_user_id or (actor.user_id if actor is not None else uid)
        )

        damage_response = None
        if damage_data is not None:
            damage_response = DNAApiResp.ok(damage_data)
        elif damage_message is not None:
            damage_response = DNAApiResp.err(damage_message)
        elif damage_calc is not None and damage_calc.message:
            damage_response = DNAApiResp.err(damage_calc.message)

        custom_panel = None
        if isinstance(self.resources, ResourceMap):
            custom_panel = self.resources.original_panel(detail.char_id)

        card_bytes, original_path = await _draw_role_detail_card(
            ctx,
            char_id,
            char_name,
            role_show,
            detail,
            con_weapon=con_weapon,
            close_weapon=close_weapon,
            ranged_weapon=ranged_weapon,
            damage_calc_response=damage_response,
            uid_hidden=uid_hidden,
            custom_panel=custom_panel,
        )
        lines = [
            detail.char_name,
            f"UID {'***' if uid_hidden else uid}",
            f"等级: {_text_value(detail.level)}",
            f"命座/等阶: {_text_value(detail.grade_level)}",
        ]
        lines.extend(f"{item.skill_name}: Lv.{item.level}" for item in detail.skills)
        lines.extend(f"溯源: {item.description}" for item in detail.traces)
        lines.extend(f"魔之楔: {item.name}" for item in detail.modes if item.name)
        lines.extend(f"{label}: {weapon.name}" for label, weapon in weapons)
        if damage_data is not None:
            for skill in damage_data.skills:
                skill_name = getattr(skill, "name", getattr(skill, "skillName", ""))
                lines.append(skill_name)
                attrs = list(getattr(skill, "damage_skill_attributes", [])) + list(
                    getattr(skill, "normal_skill_attributes", [])
                )
                for item in attrs:
                    lines.append(f"{item.key}: {item.value}")
        else:
            if damage_message:
                lines.append(damage_message)
            elif damage_calc is not None and damage_calc.message:
                lines.append(damage_calc.message)

        sections = [
            {"name": "角色头部", "items": 1},
            {"name": "角色属性", "items": 11},
            {"name": "技能", "items": len(detail.skills)},
            {"name": "溯源", "items": len(detail.traces)},
            {"name": "武器", "items": len(weapons)},
            {"name": "魔之楔", "items": len(detail.modes)},
        ]
        if damage_data is not None:
            sections.append({"name": "伤害", "items": len(damage_data.skills)})

        resources = [self._font_resource()]
        if isinstance(self.resources, ResourceMap):
            resources.append(
                {
                    "kind": "role_paint",
                    "key": str(detail.char_id),
                    "status": self.resources.get_paint_status(detail.char_id),
                    "source": f"images/role_paint/{detail.char_id}.png",
                }
            )
            resources.append(
                {
                    "kind": "original_panel",
                    "key": str(detail.char_id),
                    "status": self.resources.get_panel_status(detail.char_id),
                    "source": f"panel/{detail.char_id}.png",
                }
            )
            if original_path is None:
                original_path = custom_panel

        return self._write(
            card_bytes,
            lines=lines,
            resources=resources,
            sections=sections,
            original_image_path=original_path,
        )

    async def render_detail_legacy(
        self,
        detail: Any,
        *,
        uid: str,
        uid_hidden: bool = False,
        damage_message: str | None = None,
        overview: RoleOverview | None = None,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
    ) -> RenderedPlayerImage:
        return await self.render_detail(
            detail.char_detail,
            detail.weapons,
            detail.damage_calculation,
            uid=uid,
            uid_hidden=uid_hidden,
            damage_message=damage_message,
            overview=overview,
            actor=actor,
            target_user_id=target_user_id,
        )


__all__ = [
    "ItemTemp",
    "PlayerRenderer",
    "RenderedPlayerImage",
    "ResourceMap",
    "_attribute_payload",
    "_draw_role_detail_card",
    "_draw_role_overview_card",
    "_hero_payload",
    "_item_payload",
    "_mode_payload",
    "_role_modes_payload",
    "_section_payload",
    "_skill_payload",
    "draw_role_detail_card",
    "draw_role_info_card_core",
    "draw_role_overview_card",
    "render_role_card_image",
]
