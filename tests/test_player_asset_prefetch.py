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
        level=80,
        gradeLevel=2,
        elementIcon="https://cdn.example.test/fire.png",
        paint="https://cdn.example.test/paint.png",
        attribute=SimpleNamespace(weaponTags=["近战"]),
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

    async def fake_skill(*_args: object, **_kwargs: object) -> Image.Image:
        return await probe.image("red", (128, 128))

    async def fake_mod(*_args: object, **_kwargs: object) -> Image.Image:
        return await probe.image("green", (128, 128))

    async def fake_weapon(*_args: object, **_kwargs: object) -> Image.Image:
        return await probe.image("blue", (256, 256))

    async def fake_paint(*_args: object, **_kwargs: object) -> Image.Image:
        return await probe.image("purple", (1320, 1320))

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


class _ResolverProbe:
    def __init__(self, tmp_path) -> None:
        self.root = tmp_path
        self.calls: list[tuple[str, str, str | None]] = []
        self.paths = {
            ("role_paint", "101"): self._write("paint.png", "purple"),
            ("weapon", "201"): self._write("weapon.png", "blue"),
        }

    def _write(self, name: str, color: str):
        path = self.root / name
        Image.new("RGBA", (32, 32), color).save(path)
        return path

    async def resolve(
        self,
        kind: str,
        asset_id: str | int | None = None,
        *,
        url: str | None = None,
    ):
        key = (kind, str(asset_id))
        self.calls.append((kind, str(asset_id), url))
        return SimpleNamespace(path=self.paths.get(key))


@pytest.mark.asyncio
async def test_role_detail_uses_one_bound_asset_resolver_for_snapshot_assets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """角色立绘和武器图应从当前 lease 绑定的统一 resolver 读取。"""

    resolver = _ResolverProbe(tmp_path)
    monkeypatch.setattr(
        player_module,
        "get_paint_img",
        lambda *_args, **_kwargs: pytest.fail("不应走 legacy paint loader"),
    )
    monkeypatch.setattr(
        weapon_renderer,
        "get_weapon_img",
        lambda *_args, **_kwargs: pytest.fail("不应走 legacy weapon loader"),
    )
    monkeypatch.setattr(
        player_module,
        "get_skill_img",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=Image.new("RGBA", (1, 1))),
    )
    monkeypatch.setattr(
        player_module,
        "get_mod_img",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=Image.new("RGBA", (1, 1))),
    )
    monkeypatch.setattr(
        weapon_renderer,
        "get_mod_img",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=Image.new("RGBA", (1, 1))),
    )
    monkeypatch.setattr(
        player_module,
        "get_attr_img",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=Image.new("RGBA", (1, 1))),
    )
    monkeypatch.setattr(
        player_module,
        "build_profile_header",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={}),
    )
    monkeypatch.setattr(
        player_module._RENDERER,
        "render",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=b"rendered"),
    )

    await player_module._draw_role_detail_card(
        SimpleNamespace(user_id="user-1"),
        "101",
        "角色甲",
        SimpleNamespace(roleId="101", roleName="玩家", level=80, params=[]),
        _role_detail(),
        close_weapon=_weapon_detail(),
        asset_resolver=resolver,
    )

    assert ("role_paint", "101", "https://cdn.example.test/paint.png") in resolver.calls
    assert ("weapon", "201", "https://cdn.example.test/weapon.png") in resolver.calls
