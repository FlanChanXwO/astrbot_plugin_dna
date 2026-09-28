"""角色详情卡武器区块的用户可见属性回归。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.rendering.weapon_renderer import draw_weapon_detail_section


class _ImageLoader:
    async def weapon(self, _weapon_id: str | int, _url: str | None) -> Image.Image:
        return Image.new("RGBA", (16, 16), "white")

    async def mod(self, _mod_id: str | int, _url: str | None) -> Image.Image:
        return Image.new("RGBA", (16, 16), "white")


@pytest.mark.asyncio
async def test_weapon_detail_displays_crit_rate_and_damage_with_correct_fields() -> None:
    """cri 是暴击率、crd 是暴击伤害，武器面板不得交换两者。"""

    weapon = SimpleNamespace(
        id=201,
        icon="",
        name="测试武器",
        level=60,
        skillLevel=1,
        modes=[],
        elementName="单手剑",
        attribute=SimpleNamespace(
            atk=24,
            cri=0.12,
            crd=1.50,
            speed=1.0,
            trigger=0.5,
        ),
    )

    payload = await draw_weapon_detail_section(
        weapon,
        "同律武器",
        image_loader=_ImageLoader(),
    )
    attributes = {
        item["label"]: item["value"] for item in payload["attributes"]
    }

    assert attributes["暴击率"] == "12%"
    assert attributes["暴击伤害"] == "150%"
    assert attributes["攻击速度"] == "1.0"
    assert attributes["攻击速度"] != "100%"
    assert attributes["触发率"] == "50%"
    assert payload["skill_level"] == 1
    assert [mode["side"] for mode in payload["modes"]] == [
        "left",
        "left",
        "right",
        "right",
    ]
    assert all(
        mode["name"] == ""
        and mode["icon"] is None
        and mode["level"] is None
        for mode in payload["modes"]
    )


@pytest.mark.asyncio
async def test_weapon_detail_preserves_four_mod_display_order() -> None:
    """四个 Mod 按既有左右槽位顺序展示。"""

    weapon = SimpleNamespace(
        id=201,
        icon="",
        name="测试武器",
        level=60,
        skillLevel=1,
        modes=[
            SimpleNamespace(
                id=index, quality=1, icon="", name=f"Mod {index}", level=index
            )
            for index in range(1, 5)
        ],
        elementName="单手剑",
        attribute=SimpleNamespace(
            atk=24,
            cri=0.12,
            crd=1.50,
            speed=1.0,
            trigger=0.5,
        ),
    )

    payload = await draw_weapon_detail_section(
        weapon,
        "同律武器",
        image_loader=_ImageLoader(),
    )

    assert [(mode["name"], mode["side"]) for mode in payload["modes"]] == [
        ("Mod 1", "left"),
        ("Mod 3", "left"),
        ("Mod 4", "right"),
        ("Mod 2", "right"),
    ]
