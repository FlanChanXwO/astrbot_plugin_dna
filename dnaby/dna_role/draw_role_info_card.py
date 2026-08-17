import asyncio
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    build_profile_header,
    font_data_uri,
    image_data_uri,
    pil_image_data_uri,
)
from ..utils import dna_api
from ..utils.api.model import DNARoleForToolRes, RoleShowForTool
from ..utils.database.models import DNABind
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image import (
    get_attr_img,
    get_avatar_img,
    get_grade_img,
    get_weapon_attr_img,
    get_weapon_img,
)
from ..utils.msgs.notify import (
    dna_not_found,
    dna_peek_blocked,
    dna_token_invalid,
    dna_uid_invalid,
)
from ..utils.session import EventContext, Sender
from ..utils.utils import get_using_id, is_peek_blocked, is_uid_hidden

TEXT_PATH = Path(__file__).parent / "texture2d"
_RENDERER = HtmlRenderer()


def is_show_role_info_card():
    from ..dna_config.dna_config import DNAConfig

    return DNAConfig.get_config("RoleInfoCard").data


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
    return {
        "element": pil_image_data_uri(element.resize((element.width // 2, element.height // 2))),
        "grade": (
            pil_image_data_uri(get_grade_img(item.grade_level))
            if item.grade_level is not None
            else None
        ),
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
        ItemTemp(type="role", id=role.charId, name=role.name, level=role.level, element_icon=role.elementIcon, icon=role.icon, grade_level=role.gradeLevel, unlocked=role.unLocked)
        for role in role_show.roleChars
    ]
    close_items = [
        ItemTemp(type="weapon", id=weapon.weaponId, name=weapon.name, level=weapon.level, element_icon=weapon.elementIcon, icon=weapon.icon, grade_level=weapon.skillLevel, unlocked=weapon.unLocked)
        for weapon in role_show.closeWeapons
    ]
    lang_items = [
        ItemTemp(type="weapon", id=weapon.weaponId, name=weapon.name, level=weapon.level, element_icon=weapon.elementIcon, icon=weapon.icon, grade_level=weapon.skillLevel, unlocked=weapon.unLocked)
        for weapon in role_show.langRangeWeapons
    ]
    achievements = [
        {"label": "角色数量", "value": str(sum(item.unlocked for item in role_items))},
        {"label": "近战武器", "value": str(sum(item.unlocked for item in close_items))},
        {"label": "远程武器", "value": str(sum(item.unlocked for item in lang_items))},
    ]
    achievements.extend(
        {"label": item.paramKey, "value": item.paramValue}
        for item in role_show.params
        if item.paramKey in ("装饰数量", "魔灵数量")
    )
    achievements.append({"label": "总成就数", "value": str(role_show.roleAchv.total)})
    header_stats = [
        (item.paramKey, item.paramValue)
        for item in role_show.params
        if item.paramKey in ("总活跃天数", "游戏时长")
    ]
    header = await build_profile_header(
        ctx,
        role_show.roleId,
        role_show.roleName,
        user_level=role_show.level,
        stats=header_stats,
        avatar_user_id=ctx.user_id,
        uid_hidden=uid_hidden,
    )

    sections = [
        await _section_payload(role_items, "角色信息", show_none, TEXT_PATH / "bg" / "bg1.png"),
        await _section_payload(close_items, "近战武器", show_none, TEXT_PATH / "bg" / "bg5.png"),
        await _section_payload(lang_items, "远程武器", show_none, TEXT_PATH / "bg" / "bg4.png"),
    ]
    section_counts = [
        len(items) if show_none else sum(item.unlocked for item in items)
        for items in (role_items, close_items, lang_items)
    ]
    height = 800 + sum(70 + 320 * math.ceil(count / 5) for count in section_counts if count)

    return await _RENDERER.render(
        "cards/role_info.html.j2",
        {
            "achievements": achievements,
            "background": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "bg1.jpg"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "footer_image": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"),
            "header": header,
            "header_background": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "avatar_title_bg.png"),
            "info_bar": image_data_uri(TEXT_PATH / "info_bar.png"),
            "div_background": image_data_uri(TEXT_PATH / "div_bg.png"),
            "item_foreground": image_data_uri(TEXT_PATH / "item_fg.png"),
            "item_mask": image_data_uri(TEXT_PATH / "item_mask.png"),
            "sections": sections,
            "title_background": image_data_uri(TEXT_PATH / "title_bg.jpg"),
            "title_mask": image_data_uri(TEXT_PATH / "title_mask.png"),
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )


async def draw_role_info_card(sender: Sender, ctx: EventContext):
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
    default_role = await dna_api.get_default_role_for_tool(dna_user)
    if not default_role.is_success:
        await dna_not_found(sender, ctx, "角色列表信息")
        return

    role_show = DNARoleForToolRes.model_validate(default_role.data).roleInfo.roleShow
    show_none = is_show_role_info_card()
    uid_hidden = await is_uid_hidden(user_id, ctx.bot_id, ctx.group_id)

    card = await _draw_role_overview_card(ctx, role_show, show_none=show_none, uid_hidden=uid_hidden)
    await sender.send(card)


draw_role_overview_card = _draw_role_overview_card

