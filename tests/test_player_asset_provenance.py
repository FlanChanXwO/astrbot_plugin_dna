"""玩家卡素材 provenance 与 placeholder 回归测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.rendering import PlayerRenderer, ResourceMap, weapon_renderer
from src.infrastructure.rendering import player as player_module
from src.infrastructure.rendering.player_image_loader import PlayerImageLoader
from src.infrastructure.resources import AssetResolver
from src.utils.image_utils import ImageFetcherClosed


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


class _RuntimeDownloader:
    def __init__(self, color: str) -> None:
        self.color = color
        self.closed = False
        self.calls: list[str] = []

    async def fetch(self, url: str, target: Path, *, tag: str = "") -> Path:
        del tag
        if self.closed:
            raise ImageFetcherClosed(f"{self.color} downloader closed")
        self.calls.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (24, 24), self.color).save(target)
        return target


@pytest.mark.asyncio
async def test_role_detail_uses_one_bound_asset_resolver_for_snapshot_assets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """角色立绘和武器图应从当前 lease 绑定的统一 resolver 读取。"""

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

    generation_root = tmp_path / "generation"
    paint_path = generation_root / "images" / "role_paint" / "101.png"
    weapon_path = generation_root / "images" / "weapon" / "201.png"
    paint_path.parent.mkdir(parents=True)
    weapon_path.parent.mkdir(parents=True)
    Image.new("RGBA", (32, 32), "purple").save(paint_path)
    Image.new("RGBA", (32, 32), "blue").save(weapon_path)
    downloader = _RuntimeDownloader("gray")
    resolver = AssetResolver(
        snapshot_root=generation_root,
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    await player_module._draw_role_detail_card(
        SimpleNamespace(user_id="user-1"),
        "101",
        "角色甲",
        SimpleNamespace(roleId="101", roleName="玩家", level=80, params=[]),
        _role_detail(),
        close_weapon=_weapon_detail(),
        image_loader=PlayerImageLoader(resolver),
    )

    assert "https://cdn.example.test/paint.png" not in downloader.calls
    assert "https://cdn.example.test/weapon.png" not in downloader.calls


@pytest.mark.asyncio
async def test_player_renderer_metadata_uses_resolved_asset_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 命中时渲染 metadata 应记录真实来源，而不是静态 ResourceMap 推测。"""

    dynamic_root = tmp_path / "cache" / "assets"
    role_path = dynamic_root / "game_avatar" / "avatar_101.png"
    weapon_path = dynamic_root / "weapon" / "weapon_201.png"
    role_path.parent.mkdir(parents=True)
    weapon_path.parent.mkdir(parents=True)
    Image.new("RGBA", (32, 32), "purple").save(role_path)
    Image.new("RGBA", (32, 32), "blue").save(weapon_path)
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=dynamic_root,
        downloader=_RuntimeDownloader("unused"),
    )

    async def fake_header(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    async def fake_render(
        *_args: object,
        **_kwargs: object,
    ) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module, "build_profile_header", fake_header)
    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)

    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(
            root=tmp_path / "generation",
            fonts={"dna_fonts": font_path},
        ),
        asset_resolver=resolver,
    )
    overview = SimpleNamespace(
        role_name="测试玩家",
        role_id="role-1",
        level=42,
        params=[],
        role_chars=[
            SimpleNamespace(
                char_id=101,
                name="角色甲",
                level=80,
                element_icon="",
                icon="role://101",
                grade_level=0,
                unlocked=True,
            )
        ],
        close_weapons=[
            SimpleNamespace(
                weapon_id=201,
                name="武器甲",
                level=80,
                element_icon="",
                icon="weapon://201",
                skill_level=0,
                unlocked=True,
            )
        ],
        ranged_weapons=[],
    )

    rendered = await renderer.render_overview(overview, uid="uid-1")

    role_metadata = next(
        item
        for item in rendered.resources
        if item["kind"] == "role_avatar" and item["key"] == "101"
    )
    weapon_metadata = next(
        item
        for item in rendered.resources
        if item["kind"] == "weapon_icon" and item["key"] == "201"
    )
    assert role_metadata["source"] == "dynamic_cache"
    assert role_metadata["status"] == "provided"
    assert weapon_metadata["source"] == "dynamic_cache"
    assert weapon_metadata["status"] == "provided"
    assert rendered.incomplete is False


@pytest.mark.asyncio
async def test_player_renderer_network_assets_are_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网络下载成功后应沿用 resolver 的 download provenance，不标记占位。"""

    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=_RuntimeDownloader("blue"),
    )

    async def fake_header(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    async def fake_render(*_args: object, **_kwargs: object) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module, "build_profile_header", fake_header)
    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)
    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(
            root=tmp_path / "generation",
            fonts={"dna_fonts": font_path},
        ),
        asset_resolver=resolver,
    )

    rendered = await renderer.render_overview(
        SimpleNamespace(
            role_name="测试玩家",
            role_id="role-1",
            level=42,
            params=[],
            role_chars=[
                SimpleNamespace(
                    char_id=101,
                    name="角色甲",
                    level=80,
                    element_icon="",
                    icon="role://101",
                    grade_level=0,
                    unlocked=True,
                )
            ],
            close_weapons=[
                SimpleNamespace(
                    weapon_id=201,
                    name="武器甲",
                    level=80,
                    element_icon="",
                    icon="weapon://201",
                    skill_level=0,
                    unlocked=True,
                )
            ],
            ranged_weapons=[],
        ),
        uid="uid-1",
    )

    assert rendered.incomplete is False
    assert {
        item["source"]
        for item in rendered.resources
        if item.get("key") in {"101", "201"}
    } == {"download"}


@pytest.mark.asyncio
async def test_player_renderer_l2_paint_hit_is_not_blocked_by_unused_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情卡未使用专属面板时，不应把可选面板缺失算进 incomplete。"""

    async def fake_render(*_args: object, **_kwargs: object) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)
    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=_RuntimeDownloader("green"),
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(
            root=tmp_path / "generation",
            fonts={"dna_fonts": font_path},
        ),
        asset_resolver=resolver,
    )

    rendered = await renderer.render_detail(
        _role_detail(),
        [("近战", _weapon_detail())],
        uid="uid-1",
        target_user_id="user-1",
    )

    assert rendered.incomplete is False
    assert any(
        item["kind"] == "role_paint"
        and item["source"] == "download"
        and item["status"] == "provided"
        for item in rendered.resources
    )
    assert any(
        item["kind"] == "original_panel"
        and item["source"] == "panel/"
        and item["status"] == "fallback"
        for item in rendered.resources
    )


@pytest.mark.asyncio
async def test_player_renderer_optional_detail_element_icon_does_not_block_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情卡缺少可选元素图时，核心素材成功仍应保持完整。"""

    async def fake_render(*_args: object, **_kwargs: object) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)
    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=_RuntimeDownloader("green"),
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(
            root=tmp_path / "generation",
            fonts={"dna_fonts": font_path},
        ),
        asset_resolver=resolver,
    )
    detail = _role_detail()
    detail.elementIcon = ""
    detail.element_icon = ""

    rendered = await renderer.render_detail(
        detail,
        [("近战", _weapon_detail())],
        uid="uid-1",
        target_user_id="user-1",
    )

    assert rendered.incomplete is False
    assert not any(
        item["kind"] == "attr" and item["status"] == "missing"
        for item in rendered.resources
    )


@pytest.mark.asyncio
async def test_player_renderer_placeholder_provenance_marks_image_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """下载失败后的缺失结果必须阻止把占位卡片当作完整卡片缓存。"""

    downloader = _RuntimeDownloader("closed")
    downloader.closed = True
    resolver = AssetResolver(
        snapshot_root=tmp_path / "generation",
        dynamic_root=tmp_path / "cache" / "assets",
        downloader=downloader,
    )

    async def fake_header(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    async def fake_render(*_args: object, **_kwargs: object) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module, "build_profile_header", fake_header)
    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)
    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(
            root=tmp_path / "generation",
            fonts={"dna_fonts": font_path},
        ),
        asset_resolver=resolver,
    )

    rendered = await renderer.render_overview(
        SimpleNamespace(
            role_name="测试玩家",
            role_id="role-1",
            level=42,
            params=[],
            role_chars=[
                SimpleNamespace(
                    char_id=101,
                    name="角色甲",
                    level=80,
                    element_icon="",
                    icon="https://cdn.example.test/role.png",
                    grade_level=0,
                    unlocked=True,
                )
            ],
            close_weapons=[
                SimpleNamespace(
                    weapon_id=201,
                    name="武器甲",
                    level=80,
                    element_icon="",
                    icon="https://cdn.example.test/weapon.png",
                    skill_level=0,
                    unlocked=True,
                )
            ],
            ranged_weapons=[],
        ),
        uid="uid-1",
    )

    metadata = next(
        item
        for item in rendered.resources
        if item["kind"] == "role_avatar" and item["key"] == "101"
    )
    assert metadata["source"] == "none"
    assert metadata["status"] == "missing"
    weapon_metadata = next(
        item
        for item in rendered.resources
        if item["kind"] == "weapon_icon" and item["key"] == "201"
    )
    assert weapon_metadata["source"] == "none"
    assert weapon_metadata["status"] == "missing"
    assert rendered.incomplete is True
