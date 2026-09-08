import importlib
from pathlib import Path
from typing import Any, cast

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from src.infrastructure.rendering.damage_renderer import draw_role_damage_section
from src.infrastructure.rendering.player import (
    ItemTemp,
    _item_payload,
    _role_modes_payload,
)
from src.infrastructure.rendering.weapon_renderer import draw_weapon_detail_section
from src.modules.player.damage_service import RoleDamageBuild
from src.utils.api.damage_model import (
    AttributeBag,
    CharacterCalculateData,
    DamageResult,
    SkillAttribute,
    SkillResult,
)
from src.utils.api.model import (
    Mode,
    RoleAttribute,
    RoleDetail,
    RoleSkill,
    WeaponAttribute,
    WeaponDetail,
)
from src.utils.api.request_util import DNAApiResp

TEMPLATE_DIR = Path(__file__).parents[1] / "src" / "templates"


def _role_detail() -> RoleDetail:
    return RoleDetail(
        attribute=RoleAttribute.model_validate(
            {
                "atk": 1000,
                "maxHp": 2000,
                "maxES": 300,
                "def": 400,
                "maxSp": 100,
                "skillIntensity": "120%",
                "skillRange": "100%",
                "skillSustain": "110%",
                "skillEfficiency": "105%",
                "strongValue": "0%",
                "enmityValue": "0%",
                "weaponTags": [],
            }
        ),
        skills=[RoleSkill(skillId=1, icon="icon", level=7, skillName="主技能")],
        paint="paint",
        charId=5101,
        charName="测试角色",
        elementIcon="element",
        traces=[],
        currentVolume=0,
        sumVolume=0,
        level=80,
        icon="icon",
        gradeLevel=0,
        elementName="火",
        modes=[],
    )


def test_damage_payload_keeps_attributes_weapons_and_derived_skills() -> None:
    build = RoleDamageBuild(role_detail=_role_detail())
    calculation = CharacterCalculateData(
        baseAttribute=AttributeBag(atk=1000, hp=2000),
        finalAttribute=AttributeBag(atk=1200, hp=2000),
        damage=DamageResult(),
        skills=[
            SkillResult(
                id=1,
                name="主技能",
                normalSkillAttributes=[
                    SkillAttribute(key="倍率", value="100%", environmentValue="120%")
                ],
            ),
            SkillResult(
                id=2,
                parentId=1,
                name="完整派生技能名称",
                damageSkillAttributes=[SkillAttribute(key="伤害", value="99999")],
            ),
        ],
    )

    payload = draw_role_damage_section(
        build,
        DNAApiResp[CharacterCalculateData].ok(calculation),
    )

    attributes = payload["attributes"]
    skills = payload["skills"]
    assert isinstance(attributes, list)
    assert isinstance(skills, list)
    assert payload["width"] == 900
    assert attributes[0] == {"label": "攻击", "value": "1,000 → 1,200"}
    assert skills[0]["name"] == "主技能"
    assert skills[0]["children"][0]["name"] == "完整派生技能名称"


@pytest.mark.asyncio
async def test_weapon_and_role_mode_payloads_inline_all_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_weapon(*_: object) -> Image.Image:
        return Image.new("RGBA", (2, 2), "red")

    monkeypatch.setattr(
        "src.infrastructure.rendering.weapon_renderer.get_weapon_img", fake_weapon
    )
    weapon = WeaponDetail(
        attribute=WeaponAttribute(atk=100, crd=0.2, cri=1.5, speed=1.0, trigger=0.3),
        currentVolume=0,
        elementIcon="element",
        elementName="近战",
        icon="weapon",
        id=1,
        level=80,
        modes=[Mode(id=-1) for _ in range(4)],
        name="完整武器名称",
        skillLevel=5,
        sumVolume=0,
    )

    weapon_payload = await draw_weapon_detail_section(weapon, "近战武器")
    role_modes = await _role_modes_payload([Mode(id=-1) for _ in range(9)])

    assert weapon_payload["name"] == "完整武器名称"
    assert str(weapon_payload["icon"]).startswith("data:image/png;base64,")
    weapon_modes = weapon_payload["modes"]
    assert isinstance(weapon_modes, list)
    assert len(weapon_modes) == 4
    assert len(role_modes) == 9
    assert all(str(mode["background"]).startswith("data:image/") for mode in role_modes)


def test_role_detail_template_preserves_complete_text_and_escapes() -> None:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )
    data_uri = "data:image/png;base64,AA=="
    payload = {
        "attributes": [{"icon": data_uri, "label": "攻击<script>", "value": "1,000"}],
        "background": data_uri,
        "damage": {
            "attributes": [{"label": "技能威力", "value": "100% → 120%"}],
            "enemy": "剧目-无尽 · 第31轮",
            "error": None,
            "lineup": [{"label": "角色", "name": "完整角色名称"}],
            "restraint": "克制",
            "skills": [
                {
                    "children": [
                        {
                            "metrics": [{"label": "伤害", "value": "99999"}],
                            "name": "很长但不应截断的派生技能名称",
                        }
                    ],
                    "level": 7,
                    "metrics": [{"label": "倍率", "value": "120%"}],
                    "name": "主技能",
                }
            ],
            "weapons": [{"label": "近战", "name": "完整武器名称", "value": "12345"}],
        },
        "element_icon": data_uri,
        "font": "data:font/ttf;base64,AA==",
        "footer_text": "DNAUID",
        "grades": [{"icon": data_uri, "index": 1, "unlocked": True}],
        "header": {
            "avatar": data_uri,
            "name": "玩家",
            "uid": "1",
            "level": 60,
            "stats": [],
        },
        "hero": {"image": data_uri, "kind": "paint"},
        "role": {"grade": 1, "level": 80, "name": "角色<script>"},
        "role_modes": [],
        "skills": [{"icon": data_uri, "level": 7, "name": "完整技能名称"}],
        "weapon_sections": [],
        "width": 1000,
    }

    html = environment.get_template("cards/role_detail.html.j2").render(**payload)

    assert "width: 1000px" in html
    assert "角色&lt;script&gt;" in html
    assert "攻击&lt;script&gt;" in html
    assert "很长但不应截断的派生技能名称" in html
    assert "完整武器名称" in html
    assert "<script>" not in html


@pytest.mark.asyncio
async def test_role_overview_item_uses_legacy_grade_texture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_asset(*_: object, **__: object) -> Image.Image:
        return Image.new("RGBA", (256, 256), "red")

    role_module = cast(
        Any, importlib.import_module("src.infrastructure.rendering.player")
    )
    monkeypatch.setattr(role_module, "get_avatar_img", fake_asset)
    monkeypatch.setattr(role_module, "get_attr_img", fake_asset)
    item = ItemTemp(
        type="role",
        id=1,
        name="测试角色",
        level=80,
        element_icon="element",
        icon="avatar",
        grade_level=6,
        unlocked=True,
    )

    payload = await _item_payload(item)

    assert payload["type"] == "role"
    assert str(payload["grade"]).startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_role_overview_item_omits_grade_when_zero_or_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_asset(*_: object, **__: object) -> Image.Image:
        return Image.new("RGBA", (256, 256), "red")

    role_module = cast(
        Any, importlib.import_module("src.infrastructure.rendering.player")
    )
    monkeypatch.setattr(role_module, "get_avatar_img", fake_asset)
    monkeypatch.setattr(role_module, "get_attr_img", fake_asset)

    # 1. 解锁但 0 命座
    item_zero = ItemTemp(
        type="role",
        id=1,
        name="测试角色",
        level=80,
        element_icon="element",
        icon="avatar",
        grade_level=0,
        unlocked=True,
    )
    payload_zero = await _item_payload(item_zero)
    assert payload_zero["grade"] is None

    # 2. 未解锁但 grade_level=6
    item_locked_grade = ItemTemp(
        type="role",
        id=2,
        name="未解锁角色",
        level=0,
        element_icon="element",
        icon="avatar",
        grade_level=6,
        unlocked=False,
    )
    payload_locked = await _item_payload(item_locked_grade)
    assert payload_locked["grade"] is None

    # 3. 未解锁且 0 命座
    item_locked_zero = ItemTemp(
        type="role",
        id=3,
        name="未解锁角色0",
        level=0,
        element_icon="element",
        icon="avatar",
        grade_level=0,
        unlocked=False,
    )
    payload_locked_zero = await _item_payload(item_locked_zero)
    assert payload_locked_zero["grade"] is None
