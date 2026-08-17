from __future__ import annotations

from io import BytesIO
from pathlib import Path

from astrbot.api import logger
from PIL import Image, ImageOps

from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    build_profile_header,
    font_data_uri,
    image_data_uri,
    pil_image_data_uri,
)
from ..utils import dna_api
from ..utils.api.damage_model import CharacterCalculateData
from ..utils.api.model import (
    DNARoleDetailRes,
    DNARoleForToolRes,
    DNAWeaponDetailRes,
    Mode,
    RoleDetail,
    RoleInsForTool,
    RoleShowForTool,
    WeaponDetail,
)
from ..utils.api.request_util import DNAApiResp
from ..utils.database.models import DNABind, DNAUser
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image import (
    get_attr_img,
    get_grade_img,
    get_mod_img,
    get_paint_img,
    get_role_panel_img,
    get_skill_img,
)
from ..utils.master_char_const import MASTER_CHAR_NAME_BY_ID, is_master_char_id
from ..utils.msgs.notify import (
    dna_not_found,
    dna_not_unlocked,
    dna_peek_blocked,
    dna_token_invalid,
    dna_uid_invalid,
    send_dna_notify,
)
from ..utils.name_convert import alias_to_char_name, char_name_to_char_id
from ..utils.original_image import cache_original_image
from ..utils.session import EventContext, Sender
from ..utils.utils import get_using_id, is_peek_blocked, is_uid_hidden
from .damage_renderer import draw_role_damage_section
from .damage_service import RoleDamageBuild, calculate_role_damage
from .loadout import (
    WeaponNotFoundError,
    WeaponNotUnlockedError,
    WeaponSlotConflictError,
    resolve_weapon_loadout,
)
from .weapon_renderer import draw_weapon_detail_section

TEXT_PATH = Path(__file__).parent / "texture2d"
BACKGROUND_PATH = Path(__file__).parents[1] / "utils" / "texture2d" / "bg2.jpg"
_RENDERER = HtmlRenderer()

ATTR_SPECS = (
    ("atk", "攻击", "icon1.png"),
    ("maxHp", "生命", "icon10.png"),
    ("maxES", "护盾", "icon11.png"),
    ("defense", "防御", "icon9.png"),
    ("maxSp", "最大神志", "icon8.png"),
    ("skillIntensity", "技能威力", "icon7.png"),
    ("skillRange", "技能范围", "icon6.png"),
    ("skillSustain", "技能耐久", "icon5.png"),
    ("skillEfficiency", "技能效益", "icon4.png"),
    ("strongValue", "昂扬", "icon3.png"),
    ("enmityValue", "背水", "icon2.png"),
)


async def _load_weapon_detail(
    dna_user: DNAUser,
    weapon_id: int,
    weapon_eid: str,
) -> WeaponDetail | None:
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


def _attribute_payload(role_detail: RoleDetail) -> list[dict[str, str]]:
    return [
        {
            "background": image_data_uri(
                TEXT_PATH / f"prop_info_bar{1 if index % 2 == 0 else 2}.png"
            ),
            "icon": image_data_uri(TEXT_PATH / "icons" / icon_name),
            "label": label,
            "value": _format_attribute(getattr(role_detail.attribute, field)),
        }
        for index, (field, label, icon_name) in enumerate(ATTR_SPECS)
    ]


async def _skill_payload(role_detail: RoleDetail) -> list[dict[str, object]]:
    # 角色详情接口的前三项是旧面板展示的三个主技能，保持既有信息层级。
    return [
        {
            "icon": pil_image_data_uri(
                await get_skill_img(role_detail.charId, skill.skillName, skill.icon)
            ),
            "level": skill.level,
            "name": skill.skillName,
        }
        for skill in role_detail.skills[:3]
    ]


async def _mode_payload(mode: Mode, position: str) -> dict[str, object]:
    quality = mode.quality or 1
    payload: dict[str, object] = {
        "background": image_data_uri(TEXT_PATH / "mod" / f"mod_{position}_{quality}.png"),
        "icon": None,
        "level": None,
        "name": mode.name or "",
        "position": position,
    }
    if mode.id != -1:
        payload["icon"] = pil_image_data_uri(await get_mod_img(mode.id, mode.icon))
        payload["level"] = f"+{mode.level}" if mode.level else None
    return payload


async def _role_modes_payload(modes: list[Mode]) -> list[dict[str, object]]:
    if len(modes) < 9:
        raise RuntimeError(f"角色 Mod 槽数量不足，期望至少 9，实际为 {len(modes)}")
    order = tuple((index, "left") for index in (0, 2, 4, 6)) + tuple(
        (index, "right") for index in (1, 3, 7, 5)
    )
    payload = [await _mode_payload(modes[index], position) for index, position in order]
    payload.append(await _mode_payload(modes[-1], "center"))
    return payload


async def _hero_payload(
    char_id: str,
    role_detail: RoleDetail,
) -> tuple[Path | None, dict[str, str]]:
    role_panel = get_role_panel_img(char_id)
    if role_panel is not None:
        original_path, image = role_panel
        panel_size = (1000, 850)
        if image.width >= image.height:
            panel = ImageOps.fit(image.convert("RGBA"), panel_size, method=Image.Resampling.LANCZOS)
        else:
            portrait_size = (600, 850)
            portrait = ImageOps.fit(image.convert("RGBA"), portrait_size, method=Image.Resampling.LANCZOS)
            side_mask = Image.new("L", portrait_size, 255)
            side_fade = Image.linear_gradient("L").rotate(270, expand=True).resize((72, portrait_size[1]))
            side_mask.paste(side_fade, (portrait_size[0] - 72, 0))
            panel = Image.new("RGBA", panel_size)
            panel.alpha_composite(Image.composite(portrait, Image.new("RGBA", portrait_size), side_mask))
        bottom_mask = Image.new("L", panel_size, 255)
        bottom_fade = ImageOps.invert(Image.linear_gradient("L")).resize((panel_size[0], 72))
        bottom_mask.paste(bottom_fade, (0, panel_size[1] - 72))
        panel = Image.composite(panel, Image.new("RGBA", panel_size), bottom_mask)
        return original_path, {"image": pil_image_data_uri(panel), "kind": "panel"}
    image = await get_paint_img(char_id, role_detail.paint)
    paint = image.convert("RGBA").resize((1056, 1056), Image.Resampling.LANCZOS)
    panel = Image.new("RGBA", (1000, 850))
    panel.alpha_composite(paint, (-280, -100))
    return None, {"image": pil_image_data_uri(panel), "kind": "paint"}



async def _draw_role_detail_card(
    ctx: EventContext,
    char_id: str,
    char_name: str,
    role_show: RoleShowForTool,
    role_detail: RoleDetail,
    con_weapon: WeaponDetail | None = None,
    close_weapon: WeaponDetail | None = None,
    ranged_weapon: WeaponDetail | None = None,
    damage_calc_response: DNAApiResp[CharacterCalculateData] | None = None,
    uid_hidden: bool = False,
) -> tuple[bytes, Path | None]:
    damage_build = RoleDamageBuild(
        role_detail=role_detail,
        con_weapon_detail=con_weapon,
        close_weapon_detail=close_weapon,
        lang_range_weapon_detail=ranged_weapon,
    )
    if damage_calc_response is None:
        damage_calc_response = DNAApiResp.err("未执行伤害计算")
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

    original_path, hero = await _hero_payload(char_id, role_detail)
    header = await build_profile_header(
        ctx,
        role_show.roleId,
        role_show.roleName,
        user_level=role_show.level,
        stats=[
            (item.paramKey, item.paramValue)
            for item in role_show.params
            if item.paramKey in ("总活跃天数", "游戏时长")
        ],
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )
    grade_total = 7 if role_detail.gradeLevel >= 7 else 6
    grades = [
        {
            "background": image_data_uri(
                TEXT_PATH / ("grade_1.png" if index <= role_detail.gradeLevel else "grade_0.png")
            ),
            "icon": pil_image_data_uri(get_grade_img(index)),
            "index": index,
            "left": 50 + (index - 1) * (375 // (grade_total - 1)),
            "unlocked": index <= role_detail.gradeLevel,
        }
        for index in range(1, grade_total + 1)
    ]
    card = await _RENDERER.render(
        "cards/role_detail.html.j2",
        {
            "attributes": _attribute_payload(role_detail),
            "background": image_data_uri(BACKGROUND_PATH),
            "divider": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "div.png"),
            "damage": damage,
            "element_icon": pil_image_data_uri(
                await get_attr_img(char_id, role_detail.elementIcon)
            ),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_image": image_data_uri(
                Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"
            ),
            "grades": grades,
            "header": header,
            "hero": hero,
            "point": image_data_uri(TEXT_PATH / "point.png"),
            "profile_background": image_data_uri(
                Path(__file__).parents[1] / "utils" / "texture2d" / "avatar_title_bg.png"
            ),
            "role": {
                "grade": role_detail.gradeLevel,
                "grade_icon": pil_image_data_uri(get_grade_img(role_detail.gradeLevel)),
                "level": role_detail.level,
                "name": char_name,
            },
            "role_modes": await _role_modes_payload(role_detail.modes),
            "skills": await _skill_payload(role_detail),
            "skill_background": image_data_uri(TEXT_PATH / "skill_bg.png"),
            "weapon_sections": weapon_sections,
            "width": 1000,
        },
        RenderSpec(width=1000, full_page=True, image_format="jpeg"),
    )
    return card, original_path


async def draw_role_card(
    sender: Sender,
    ctx: EventContext,
    char_name: str,
    *,
    weapon_names: tuple[str, ...] = (),
) -> None:
    user_id = await get_using_id(ctx)
    if is_peek_blocked(ctx, user_id):
        await dna_peek_blocked(sender, ctx)
        return
    uid = await DNABind.get_uid_by_game(user_id, ctx.bot_id)
    if not uid:
        await dna_uid_invalid(sender, ctx)
        return
    dna_user = await dna_api.get_dna_user(uid, user_id, ctx.bot_id)
    if not dna_user:
        await dna_token_invalid(sender, ctx)
        return

    real_char_name = alias_to_char_name(char_name)
    if not real_char_name:
        await dna_not_found(sender, ctx, f"角色别名【{char_name}】")
        return
    char_id = char_name_to_char_id(real_char_name)
    if not char_id:
        await dna_not_found(sender, ctx, f"角色【{char_name}】的CharId")
        return
    char_name = real_char_name

    default_role_response = await dna_api.get_default_role_for_tool(dna_user)
    if not default_role_response.is_success:
        await dna_not_found(sender, ctx, "角色列表信息")
        return
    role_show = DNARoleForToolRes.model_validate(default_role_response.data).roleInfo.roleShow

    try:
        weapon_loadout = resolve_weapon_loadout(
            role_show.closeWeapons,
            role_show.langRangeWeapons,
            weapon_names,
        )
    except WeaponNotFoundError as error:
        await dna_not_found(sender, ctx, f"展柜武器【{error.weapon_name}】")
        return
    except WeaponNotUnlockedError as error:
        await dna_not_unlocked(sender, ctx, f"当前展柜武器【{error.weapon_name}】")
        return
    except WeaponSlotConflictError as error:
        await send_dna_notify(sender, ctx, f"不能同时携带两把{error.slot.value}武器")
        return

    if is_master_char_id(char_id):
        role_simple: RoleInsForTool | None = next(
            (item for item in role_show.roleChars if is_master_char_id(item.charId)),
            None,
        )
        if role_simple is not None:
            char_id = str(role_simple.charId)
            char_name = MASTER_CHAR_NAME_BY_ID.get(char_id, char_name)
    else:
        role_simple = next(
            (item for item in role_show.roleChars if str(item.charId) == char_id),
            None,
        )
    if role_simple is None:
        await dna_not_found(sender, ctx, f"展柜角色【{char_name}】")
        return
    if not role_simple.unLocked or not role_simple.charEid:
        await dna_not_unlocked(sender, ctx, f"当前展柜角色【{char_name}】")
        return

    role_response = await dna_api.get_role_detail(dna_user, char_id, role_simple.charEid)
    if not role_response.is_success:
        await dna_not_found(sender, ctx, f"角色【{char_name}】详情")
        return
    role_detail = DNARoleDetailRes.model_validate(role_response.data).charDetail

    con_weapon: WeaponDetail | None = None
    if role_detail.conWeaponId is not None and role_detail.conWeaponEid is not None:
        con_weapon = await _load_weapon_detail(
            dna_user,
            role_detail.conWeaponId,
            role_detail.conWeaponEid,
        )

    close_weapon: WeaponDetail | None = None
    if weapon_loadout.close_weapon is not None:
        close_weapon = await _load_weapon_detail(
            dna_user,
            weapon_loadout.close_weapon.weapon_id,
            weapon_loadout.close_weapon.weapon_eid,
        )
        if close_weapon is None:
            await dna_not_found(sender, ctx, f"近战武器【{weapon_loadout.close_weapon.name}】详情")
            return

    ranged_weapon: WeaponDetail | None = None
    if weapon_loadout.ranged_weapon is not None:
        ranged_weapon = await _load_weapon_detail(
            dna_user,
            weapon_loadout.ranged_weapon.weapon_id,
            weapon_loadout.ranged_weapon.weapon_eid,
        )
        if ranged_weapon is None:
            await dna_not_found(sender, ctx, f"远程武器【{weapon_loadout.ranged_weapon.name}】详情")
            return

    damage_build = RoleDamageBuild(
        role_detail=role_detail,
        con_weapon_detail=con_weapon,
        close_weapon_detail=close_weapon,
        lang_range_weapon_detail=ranged_weapon,
    )
    damage_calc = await calculate_role_damage(dna_user, damage_build)
    uid_hidden = await is_uid_hidden(user_id, ctx.bot_id, ctx.group_id)

    card, original_path = await _draw_role_detail_card(
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
    message_ids = await sender.send(card, wait_recall=True)
    logger.debug(f"[DNA Detail] role panel message_ids={message_ids}")
    cache_original_image(message_ids, original_path)


draw_role_detail_card = _draw_role_detail_card


async def render_role_card_image(
    role_detail: RoleDetail,
    weapons: list[tuple[str, WeaponDetail]],
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

    role_show = RoleShowForTool.model_validate(
        {
            "roleId": str(role_detail.charId),
            "roleName": role_detail.charName,
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
        else DNAApiResp.err(damage_message or "未执行伤害计算")
    )
    card_bytes, _ = await _draw_role_detail_card(
        ctx,
        str(role_detail.charId),
        role_detail.charName,
        role_show,
        role_detail,
        con_weapon=con_weapon,
        close_weapon=close_weapon,
        ranged_weapon=ranged_weapon,
        damage_calc_response=damage_calc,
        uid_hidden=uid_hidden,
    )
    return Image.open(BytesIO(card_bytes)).convert("RGBA")



