"""角色详情卡的武器区块 payload 构建。"""

from __future__ import annotations

from pathlib import Path

from ..rendering import image_data_uri, pil_image_data_uri
from ..utils.api.model import Mode, WeaponDetail
from ..utils.image import get_mod_img, get_weapon_img

TEXT_PATH = Path(__file__).parent / "texture2d"


def _mode_quality(mode: Mode) -> int:
    if mode.id == -1:
        return 1
    if mode.quality is None:
        raise RuntimeError(f"武器 Mod {mode.id} 缺少品质")
    return mode.quality


async def _mode_payload(mode: Mode, side: str) -> dict[str, object]:
    quality = _mode_quality(mode)
    payload: dict[str, object] = {
        "background": image_data_uri(TEXT_PATH / f"mod/mod_{side}_{quality}.png"),
        "icon": None,
        "level": None,
        "name": mode.name or "",
        "side": side,
    }
    if mode.id == -1:
        return payload
    if mode.id <= 0:
        raise RuntimeError(f"武器 Mod ID 非法: {mode.id}")
    if mode.name is None or mode.icon is None or mode.level is None:
        raise RuntimeError(f"武器 Mod {mode.id} 详情不完整")
    payload["icon"] = pil_image_data_uri(await get_mod_img(mode.id, mode.icon))
    payload["level"] = f"+{mode.level}" if mode.level > 0 else None
    return payload


def _mode_order(modes: list[Mode]) -> list[tuple[Mode, str]]:
    if len(modes) == 4:
        indexes = ((0, "left"), (2, "left"), (3, "right"), (1, "right"))
    elif len(modes) == 8:
        indexes = tuple((index, "left") for index in (0, 2, 4, 6)) + tuple(
            (index, "right") for index in (1, 3, 7, 5)
        )
    else:
        raise ValueError(f"武器 Mod 槽数量必须为 4 或 8，实际为 {len(modes)}")
    return [(modes[index], side) for index, side in indexes]


async def draw_weapon_detail_section(
    weapon_detail: WeaponDetail,
    title: str,
) -> dict[str, object]:
    """保留旧函数签名，返回 HTML 模板使用的武器区块 payload。"""

    weapon_image = await get_weapon_img(weapon_detail.id, weapon_detail.icon)
    attr = weapon_detail.attribute
    attr_specs = (
        ("武器类型", weapon_detail.elementName, "icon16.png"),
        ("攻击", f"{attr.atk:,}", "icon17.png"),
        ("暴击率", f"{attr.crd:.0%}", "icon13.png"),
        ("暴击伤害", f"{attr.cri:.0%}", "icon12.png"),
        ("攻击速度", f"{attr.speed:.0%}", "icon14.png"),
        ("触发率", f"{attr.trigger:.0%}", "icon15.png"),
    )
    attributes = [
        {
            "icon": image_data_uri(TEXT_PATH / f"icons/{icon_name}"),
            "label": label,
            "value": value,
        }
        for label, value, icon_name in attr_specs
    ]
    modes = [await _mode_payload(mode, side) for mode, side in _mode_order(weapon_detail.modes)]
    return {
        "attribute_background": image_data_uri(TEXT_PATH / "weapon_attr.png"),
        "attributes": attributes,
        "icon": pil_image_data_uri(weapon_image),
        "level": weapon_detail.level,
        "modes": modes,
        "name": weapon_detail.name,
        "skill_level": weapon_detail.skillLevel,
        "title": title,
        "weapon_background": image_data_uri(TEXT_PATH / "weapon_bg.png"),
        "width": 1000,
    }
