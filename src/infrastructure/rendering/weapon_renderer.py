"""角色详情卡的武器区块 payload 构建。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from PIL import Image

from ...utils.api.model import Mode, WeaponDetail
from ...utils.image import get_mod_img, get_weapon_img
from .assets import image_data_uri, pil_image_data_uri

TEXT_PATH = Path(__file__).parents[2] / "resources" / "textures" / "detail"


class WeaponImageLoader(Protocol):
    """武器区块所需的异步图片加载边界。"""

    async def weapon(self, weapon_id: str | int, url: str | None) -> Image.Image:
        """读取武器图。"""

    async def mod(self, mod_id: str | int, url: str | None) -> Image.Image:
        """读取武器 Mod 图。"""


def _mode_quality(mode: Mode) -> int:
    mode_id = getattr(mode, "id", -1)
    if mode_id == -1:
        return 1
    quality = getattr(mode, "quality", None)
    if quality is None:
        raise RuntimeError(f"武器 Mod {mode_id} 缺少品质")
    return quality


async def _mode_payload(
    mode: Mode,
    side: str,
    *,
    image_loader: WeaponImageLoader | None = None,
) -> dict[str, object]:
    mode_id = getattr(mode, "id", -1)
    quality = _mode_quality(mode)
    payload: dict[str, object] = {
        "background": image_data_uri(TEXT_PATH / f"mod/mod_{side}_{quality}.png"),
        "icon": None,
        "level": None,
        "name": getattr(mode, "name", "") or "",
        "side": side,
    }
    if mode_id == -1:
        return payload
    if mode_id <= 0:
        raise RuntimeError(f"武器 Mod ID 非法: {mode_id}")
    name = getattr(mode, "name", None)
    icon = getattr(mode, "icon", None)
    level = getattr(mode, "level", None)
    if name is None or icon is None or level is None:
        raise RuntimeError(f"武器 Mod {mode_id} 详情不完整")
    image = (
        await get_mod_img(mode_id, icon)
        if image_loader is None
        else await image_loader.mod(mode_id, icon)
    )
    payload["icon"] = pil_image_data_uri(image)
    payload["level"] = f"+{level}" if level > 0 else None
    return payload


def _mode_order(modes: list[Mode]) -> list[tuple[Mode, str]]:
    if len(modes) <= 4:
        padded = list(modes) + [Mode(id=-1) for _ in range(4 - len(modes))]
        indexes = ((0, "left"), (2, "left"), (3, "right"), (1, "right"))
        return [(padded[index], side) for index, side in indexes]
    else:
        padded = list(modes[:8]) + [Mode(id=-1) for _ in range(max(0, 8 - len(modes)))]
        indexes = tuple((index, "left") for index in (0, 2, 4, 6)) + tuple(
            (index, "right") for index in (1, 3, 7, 5)
        )
        return [(padded[index], side) for index, side in indexes]


async def draw_weapon_detail_section(
    weapon_detail: WeaponDetail,
    title: str,
    *,
    image_loader: WeaponImageLoader | None = None,
) -> dict[str, object]:
    """保留旧函数签名，返回 HTML 模板使用的武器区块 payload。"""

    weapon_id = getattr(weapon_detail, "id", getattr(weapon_detail, "weapon_id", 0))
    weapon_icon = getattr(weapon_detail, "icon", "")
    weapon_image_coro = (
        get_weapon_img(weapon_id, weapon_icon)
        if image_loader is None
        else image_loader.weapon(weapon_id, weapon_icon)
    )
    raw_modes = getattr(weapon_detail, "modes", [])
    mode_payloads_coro = asyncio.gather(
        *(
            _mode_payload(mode, side, image_loader=image_loader)
            for mode, side in _mode_order(raw_modes)
        )
    )
    weapon_image, modes = await asyncio.gather(
        weapon_image_coro,
        mode_payloads_coro,
    )
    attr = getattr(weapon_detail, "attribute", None)
    atk = getattr(attr, "atk", 0) if attr else 0
    crd = getattr(attr, "crd", 0.0) if attr else 0.0
    cri = getattr(attr, "cri", 0.0) if attr else 0.0
    speed = getattr(attr, "speed", 0.0) if attr else 0.0
    trigger = getattr(attr, "trigger", 0.0) if attr else 0.0
    element_name = getattr(
        weapon_detail, "elementName", getattr(weapon_detail, "element_name", "")
    )
    attr_specs = (
        ("武器类型", element_name, "icon16.png"),
        ("攻击", f"{atk:,}", "icon17.png"),
        ("暴击率", f"{crd:.0%}", "icon13.png"),
        ("暴击伤害", f"{cri:.0%}", "icon12.png"),
        ("攻击速度", f"{speed:.0%}", "icon14.png"),
        ("触发率", f"{trigger:.0%}", "icon15.png"),
    )
    attributes = [
        {
            "icon": image_data_uri(TEXT_PATH / f"icons/{icon_name}"),
            "label": label,
            "value": value,
        }
        for label, value, icon_name in attr_specs
    ]
    return {
        "attribute_background": image_data_uri(TEXT_PATH / "weapon_attr.png"),
        "attributes": attributes,
        "icon": pil_image_data_uri(weapon_image),
        "level": getattr(weapon_detail, "level", 0),
        "modes": modes,
        "name": getattr(weapon_detail, "name", ""),
        "skill_level": getattr(
            weapon_detail, "skillLevel", getattr(weapon_detail, "skill_level", 0)
        ),
        "title": title,
        "weapon_background": image_data_uri(TEXT_PATH / "weapon_bg.png"),
        "width": 1000,
    }
