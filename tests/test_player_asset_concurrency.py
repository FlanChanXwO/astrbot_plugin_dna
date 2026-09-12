"""角色详情素材并发准备回归测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.rendering import player as player_module
from src.infrastructure.rendering import weapon_renderer


class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0

    async def image(self, color: str, size: tuple[int, int]) -> Image.Image:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0.01)
            return Image.new("RGBA", size, color)
        finally:
            self.active -= 1


def _role_detail() -> SimpleNamespace:
    return SimpleNamespace(
        charId=101,
        charName="角色甲",
        char_id=101,
        char_name="角色甲",
        level=80,
        gradeLevel=2,
        grade_level=2,
        elementIcon="https://cdn.example.test/fire.png",
        paint="https://cdn.example.test/paint.png",
        attribute=SimpleNamespace(weaponTags=["近战"], weapon_tags=["近战"]),
        traces=[],
        skills=[
            SimpleNamespace(
                skillName=f"技能{index}",
                skill_name=f"技能{index}",
                icon=f"https://cdn.example.test/skill-{index}.png",
                level=index + 1,
            )
            for index in range(3)
        ],
        modes=[
            SimpleNamespace(
                id=3000 + index,
                icon=f"https://cdn.example.test/mod-{index}.png",
                quality=1,
                name=f"魔之楔{index}",
                level=index + 1,
            )
            for index in range(3)
        ],
    )


def _weapon_detail() -> SimpleNamespace:
    return SimpleNamespace(
        id=201,
        weapon_id=201,
        icon="https://cdn.example.test/weapon.png",
        name="近战甲",
        level=80,
        skillLevel=5,
        modes=[
            SimpleNamespace(
                id=4000 + index,
                icon=f"https://cdn.example.test/weapon-mod-{index}.png",
                quality=1,
                name=f"武器楔{index}",
                level=index + 1,
            )
            for index in range(2)
        ],
        attribute=SimpleNamespace(atk=777, crd=0.1, cri=1.5, speed=0.2, trigger=0.3),
        elementName="近战",
    )


@pytest.mark.asyncio
async def test_role_detail_prefetches_independent_assets_concurrently_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """冷缓存素材应并发加载，组装后的技能、魔之楔和武器顺序不变。"""

    probe = _ConcurrencyProbe()
    captured: dict[str, object] = {}
    active_categories: dict[str, int] = {}
    cross_category_overlap = False

    async def categorized_image(
        category: str,
        color: str,
        size: tuple[int, int],
    ) -> Image.Image:
        nonlocal cross_category_overlap
        active_categories[category] = active_categories.get(category, 0) + 1
        if active_categories.get("paint", 0) and active_categories.get("weapon", 0):
            cross_category_overlap = True
        try:
            return await probe.image(color, size)
        finally:
            active_categories[category] -= 1
            if active_categories[category] == 0:
                del active_categories[category]

    async def fake_skill(*_args: object, **_kwargs: object) -> Image.Image:
        return await categorized_image("skill", "red", (128, 128))

    async def fake_mod(*_args: object, **_kwargs: object) -> Image.Image:
        return await categorized_image("mod", "green", (128, 128))

    async def fake_weapon(*_args: object, **_kwargs: object) -> Image.Image:
        return await categorized_image("weapon", "blue", (256, 256))

    async def fake_paint(*_args: object, **_kwargs: object) -> Image.Image:
        return await categorized_image("paint", "purple", (1320, 1320))

    async def fake_attr(*_args: object, **_kwargs: object) -> Image.Image:
        return await probe.image("yellow", (128, 128))

    async def fake_header(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    async def fake_render(
        _template: str,
        context: dict[str, object],
        _spec: object,
    ) -> bytes:
        captured.update(context)
        return b"rendered"

    monkeypatch.setattr(player_module, "get_skill_img", fake_skill)
    monkeypatch.setattr(player_module, "get_mod_img", fake_mod)
    monkeypatch.setattr(player_module, "get_weapon_img", fake_weapon)
    monkeypatch.setattr(player_module, "get_paint_img", fake_paint)
    monkeypatch.setattr(player_module, "get_attr_img", fake_attr)
    monkeypatch.setattr(weapon_renderer, "get_mod_img", fake_mod)
    monkeypatch.setattr(weapon_renderer, "get_weapon_img", fake_weapon)
    monkeypatch.setattr(player_module, "build_profile_header", fake_header)
    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)

    await player_module._draw_role_detail_card(
        SimpleNamespace(user_id="user-1"),
        "101",
        "角色甲",
        SimpleNamespace(roleId="101", roleName="玩家", level=80, params=[]),
        _role_detail(),
        close_weapon=_weapon_detail(),
    )

    assert probe.maximum > 1
    assert cross_category_overlap
    assert [item["name"] for item in captured["skills"]] == [
        "技能0",
        "技能1",
        "技能2",
    ]
    assert [item["name"] for item in captured["role_modes"] if item["name"]] == [
        "魔之楔0",
        "魔之楔2",
        "魔之楔1",
    ]
    sections = captured["weapon_sections"]
    assert [item["title"] for item in sections] == ["近战武器"]
    assert [item["name"] for item in sections[0]["modes"] if item["name"]] == [
        "武器楔0",
        "武器楔1",
    ]
