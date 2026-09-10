"""角色详情卡的武器区块 payload 构建。"""

from __future__ import annotations

from ...utils.api.model import Mode, WeaponDetail
from ...utils.image import get_mod_img, get_weapon_img
from .assets import pil_image_data_uri
from .legacy_assets import DETAIL_TEXT_PATH
from .legacy_assets import legacy_image_data_uri as image_data_uri
from .runtime_assets import AssetResolverLike, resolved_image_data_uri, resource_record

TEXT_PATH = DETAIL_TEXT_PATH


def _mode_quality(mode: Mode) -> int:
    mode_id = getattr(mode, "id", -1)
    if mode_id == -1:
        return 1
    quality = getattr(mode, "quality", None)
    if quality is None:
        raise RuntimeError(f"武器 Mod {mode_id} 缺少品质")
    return quality


def _resolved_image(
    resolver: AssetResolverLike,
    logical_key: str,
    *,
    label: str,
    resources: list[dict[str, str]] | None = None,
    kind: str = "texture",
) -> str:
    """通过请求级 resolver 生成武器区块图片 URI。"""

    uri, asset = resolved_image_data_uri(resolver, logical_key, label=label)
    if resources is not None:
        resources.append(resource_record(kind, logical_key, asset, source=logical_key))
    return uri


async def _mode_payload(
    mode: Mode,
    side: str,
    *,
    asset_resolver: AssetResolverLike | None = None,
    resources: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    mode_id = getattr(mode, "id", -1)
    quality = _mode_quality(mode)
    if asset_resolver is None:
        background = image_data_uri(TEXT_PATH / f"mod/mod_{side}_{quality}.png")
    else:
        background = _resolved_image(
            asset_resolver,
            f"texture.detail.mod:{side}:{quality}",
            label=f"mod-{side}-{quality}",
            resources=resources,
        )
    payload: dict[str, object] = {
        "background": background,
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
    if asset_resolver is None:
        payload["icon"] = pil_image_data_uri(await get_mod_img(mode_id, icon))
    else:
        payload["icon"] = _resolved_image(
            asset_resolver,
            f"image:mod:{mode_id}",
            label=f"mod-{mode_id}",
            resources=resources,
            kind="mod_icon",
        )
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
    asset_resolver: AssetResolverLike | None = None,
    resources: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """返回 HTML 模板使用的武器区块 payload。"""

    weapon_id = getattr(weapon_detail, "id", getattr(weapon_detail, "weapon_id", 0))
    weapon_icon = getattr(weapon_detail, "icon", "")
    if asset_resolver is None:
        weapon_image = pil_image_data_uri(await get_weapon_img(weapon_id, weapon_icon))
    else:
        weapon_image = _resolved_image(
            asset_resolver,
            f"image:weapon:{weapon_id}",
            label=f"weapon-{weapon_id}",
            resources=resources,
            kind="weapon_icon",
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
    if asset_resolver is None:
        attributes = [
            {
                "icon": image_data_uri(TEXT_PATH / f"icons/{icon_name}"),
                "label": label,
                "value": value,
            }
            for label, value, icon_name in attr_specs
        ]
        attribute_background = image_data_uri(TEXT_PATH / "weapon_attr.png")
        weapon_background = image_data_uri(TEXT_PATH / "weapon_bg.png")
    else:
        attributes = [
            {
                "icon": _resolved_image(
                    asset_resolver,
                    f"texture.detail.icon:{icon_name}",
                    label=f"weapon-attribute-{icon_name}",
                    resources=resources,
                ),
                "label": label,
                "value": value,
            }
            for label, value, icon_name in attr_specs
        ]
        attribute_background = _resolved_image(
            asset_resolver,
            "texture.detail.weapon_attr",
            label="weapon-attribute-background",
            resources=resources,
        )
        weapon_background = _resolved_image(
            asset_resolver,
            "texture.detail.weapon_bg",
            label="weapon-background",
            resources=resources,
        )
    raw_modes = getattr(weapon_detail, "modes", [])
    modes = [
        await _mode_payload(
            mode,
            side,
            asset_resolver=asset_resolver,
            resources=resources,
        )
        for mode, side in _mode_order(raw_modes)
    ]
    return {
        "attribute_background": attribute_background,
        "attributes": attributes,
        "icon": weapon_image,
        "level": getattr(weapon_detail, "level", 0),
        "modes": modes,
        "name": getattr(weapon_detail, "name", ""),
        "skill_level": getattr(
            weapon_detail, "skillLevel", getattr(weapon_detail, "skill_level", 0)
        ),
        "title": title,
        "weapon_background": weapon_background,
        "width": 1000,
    }
