"""玩家图片加载器的缓存、下载隔离和渲染路由回归测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.rendering import PlayerRenderer, ResourceMap
from src.infrastructure.rendering import (
    player_image_loader as player_image_loader_module,
)
from src.infrastructure.rendering import player as player_module
from src.infrastructure.rendering.player_image_loader import PlayerImageLoader
from src.infrastructure.resources import AssetResolver
from src.utils.image_utils import ImageFetcherClosed


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
@pytest.mark.parametrize("asset_id", ("", "   "))
async def test_player_image_loader_rejects_empty_cache_components(
    tmp_path: Path,
    asset_id: str,
) -> None:
    """空或全空白素材 ID 不能生成无效的动态缓存文件名。"""

    downloader = _RuntimeDownloader("red")
    loader = PlayerImageLoader(
        AssetResolver(dynamic_root=tmp_path / "assets", downloader=downloader)
    )

    with pytest.raises(ValueError, match="动态素材标识不能是路径段"):
        await loader.attr(asset_id, "https://cdn.example.test/attr.png")


@pytest.mark.asyncio
async def test_player_image_loader_uses_distinct_url_cache_targets(
    tmp_path: Path,
) -> None:
    """不同版本的同名 URL 素材不能复用同一属性图缓存文件。"""

    downloader = _RuntimeDownloader("red")
    loader = PlayerImageLoader(
        AssetResolver(dynamic_root=tmp_path / "assets", downloader=downloader)
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
        player_image_loader_module,
        "get_mod_img",
        lambda *_args, **_kwargs: pytest.fail("不应通过全局 legacy fetcher 加载 Mod"),
    )
    downloader_a = _RuntimeDownloader("red")
    downloader_b = _RuntimeDownloader("blue")
    resolver_a = AssetResolver(dynamic_root=tmp_path / "a", downloader=downloader_a)
    resolver_b = AssetResolver(dynamic_root=tmp_path / "b", downloader=downloader_b)
    loader_a = PlayerImageLoader(resolver_a)
    _loader_b = PlayerImageLoader(resolver_b)
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
