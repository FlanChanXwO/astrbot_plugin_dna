"""角色详情素材并发准备回归测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.rendering import PlayerRenderer, ResourceMap, weapon_renderer
from src.infrastructure.rendering import player as player_module
from src.infrastructure.resources import AssetResolver, ResolvedAsset
from src.utils.image_utils import ImageFetcherClosed


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
        asset_id: str | int,
        *,
        url: str | None = None,
    ) -> ResolvedAsset:
        key = (kind, str(asset_id))
        self.calls.append((kind, str(asset_id), url))
        path = self.paths.get(key)
        return ResolvedAsset(
            path=path,
            source="dynamic_cache" if path is not None else "none",
            status="provided" if path is not None else "missing",
            incomplete=path is None,
            kind=kind,
            asset_id=str(asset_id),
        )


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


class _RuntimeResolver:
    def __init__(self, root: Path, downloader: _RuntimeDownloader) -> None:
        self.dynamic_root = root
        self.downloader = downloader


@pytest.mark.asyncio
async def test_player_image_loader_uses_distinct_url_cache_targets(
    tmp_path: Path,
) -> None:
    """不同版本的同名 URL 素材不能复用同一属性图缓存文件。"""

    downloader = _RuntimeDownloader("red")
    loader = player_module._PlayerImageLoader(
        _RuntimeResolver(tmp_path / "assets", downloader)
    )
    url_v2 = "https://cdn.example.test/icons/fire.v2.icon.png"
    url_v3 = "https://cdn.example.test/icons/fire.v3.icon.png"

    await loader.attr(None, url_v2)
    await loader.attr(None, url_v3)

    cached_files = sorted((tmp_path / "assets" / "attr").glob("*.png"))
    assert len(cached_files) == 2
    assert downloader.calls == [url_v2, url_v3]


@pytest.mark.asyncio
async def test_player_image_loader_keeps_runtime_downloader_isolated_after_peer_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一个 runtime 关闭后，另一个 runtime 的未迁移素材仍走自己的 downloader。"""

    monkeypatch.setattr(
        player_module,
        "get_mod_img",
        lambda *_args, **_kwargs: pytest.fail("不应通过全局 legacy fetcher 加载 Mod"),
    )
    downloader_a = _RuntimeDownloader("red")
    downloader_b = _RuntimeDownloader("blue")
    resolver_a = _RuntimeResolver(tmp_path / "a", downloader_a)
    resolver_b = _RuntimeResolver(tmp_path / "b", downloader_b)
    loader_a = player_module._PlayerImageLoader(resolver_a)
    _loader_b = player_module._PlayerImageLoader(resolver_b)
    downloader_b.closed = True

    image = await loader_a.mod(7001, "https://cdn.example.test/mod.png")
    skill_image = await loader_a.skill(
        101,
        "技能 A",
        "https://cdn.example.test/skill.png",
    )

    assert image.getpixel((0, 0))[:3] == (255, 0, 0)
    assert skill_image.getpixel((0, 0))[:3] == (255, 0, 0)
    assert downloader_a.calls == [
        "https://cdn.example.test/mod.png",
        "https://cdn.example.test/skill.png",
    ]
    assert (tmp_path / "a" / "skill" / "101" / "skill_技能 A.png").is_file()


@pytest.mark.asyncio
async def test_player_renderer_routes_overview_assets_through_current_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常玩家卡链路的头像、属性图和资料头都不读取全局 downloader。"""

    async def fail_legacy(*_args: object, **_kwargs: object) -> Image.Image:
        return pytest.fail("正常 PlayerRenderer 不应调用全局 legacy 图片入口")

    for name in (
        "get_avatar_img",
        "get_attr_img",
        "get_weapon_attr_img",
        "get_weapon_img",
    ):
        monkeypatch.setattr(player_module, name, fail_legacy)

    async def fake_render(*_args: object, **_kwargs: object) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (24, 24), "white").save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(player_module._RENDERER, "render", fake_render)
    downloader_a = _RuntimeDownloader("red")
    downloader_b = _RuntimeDownloader("blue")
    downloader_b.closed = True
    resolver_a = AssetResolver(
        dynamic_root=tmp_path / "a",
        downloader=downloader_a,
    )
    _resolver_b = AssetResolver(
        dynamic_root=tmp_path / "b",
        downloader=downloader_b,
    )
    font_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "fonts"
        / "dna_fonts.ttf"
    )
    renderer = PlayerRenderer(
        tmp_path / "rendered",
        ResourceMap(fonts={"dna_fonts": font_path}),
        asset_resolver=resolver_a,
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
                    element_icon="https://cdn.example.test/role-attr.png",
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
                    element_icon="https://cdn.example.test/weapon-attr.png",
                    icon="https://cdn.example.test/weapon.png",
                    skill_level=0,
                    unlocked=True,
                )
            ],
            ranged_weapons=[],
        ),
        uid="uid-1",
        target_user_id="user-1",
    )

    assert rendered.incomplete is False
    assert {
        "role.png",
        "role-attr.png",
        "weapon.png",
        "weapon-attr.png",
    }.issubset({url.rsplit("/", 1)[-1] for url in downloader_a.calls})
    assert any("qlogo.cn" in url for url in downloader_a.calls)
