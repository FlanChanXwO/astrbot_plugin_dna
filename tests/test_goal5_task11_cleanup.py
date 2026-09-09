"""Task 11：大型本地资源删除后的 bootstrap 与降级契约。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

from src import bootstrap
from src.infrastructure.rendering import fonts as fonts_module
from src.infrastructure.rendering import help as help_module
from src.infrastructure.rendering import payloads
from src.utils import image as image_module
from src.utils.session import EventContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MIGRATED_LOCAL_ROOTS = (
    PROJECT_ROOT / "src/resources/fonts",
    PROJECT_ROOT / "src/utils/fonts",
    *(PROJECT_ROOT / "src/resources/textures" / name for name in (
        "ann",
        "calendar",
        "common",
        "detail",
        "guide",
        "help",
        "mh",
        "role",
        "sign",
        "stamina",
        "wiki",
    )),
)


def test_migrated_large_resource_roots_are_not_bundled() -> None:
    """完整字体与已接管纹理不得继续随插件发布。"""

    assert all(not path.exists() for path in MIGRATED_LOCAL_ROOTS)


def test_bootstrap_allowlist_points_to_retained_small_texture_tree() -> None:
    """无 snapshot 只保留 texture2d 中的数字 bootstrap。"""

    expected_keys = {f"texture.common.number.{digit}" for digit in range(11)}

    assert set(bootstrap._BOOTSTRAP_ALLOWLIST) == expected_keys
    assert all(
        bootstrap._BOOTSTRAP_ALLOWLIST[key]
        == PROJECT_ROOT / "src/utils/texture2d" / "number" / f"{key.rsplit('.', 1)[1]}.png"
        for key in expected_keys
    )
    assert all(path.is_file() for path in bootstrap._BOOTSTRAP_ALLOWLIST.values())


def test_profile_header_uses_retained_small_texture_tree() -> None:
    """资料头的少量装饰图保留在本地小 bootstrap，而非大型纹理目录。"""

    assert payloads.TEXTURE_PATH == PROJECT_ROOT / "src/utils/texture2d"


@pytest.mark.asyncio
async def test_avatar_title_does_not_require_deleted_legacy_font_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧头像标题 helper 在完整字体树删除后仍能使用 Pillow fallback。"""

    async def fake_avatar(*_: object, **__: object) -> Image.Image:
        return Image.new("RGBA", (190, 190), (40, 80, 120, 255))

    monkeypatch.setattr(image_module, "get_event_avatar", fake_avatar)
    monkeypatch.setitem(sys.modules, "src.utils.fonts.dna_fonts", None)

    rendered = await image_module.get_avatar_title_img(
        EventContext(user_id="user-1"),
        uid="1001",
        name="测试角色",
        user_level=3,
        other_info=[("攻击", "100"), ("防御", "200")],
    )

    assert rendered.mode == "RGBA"
    assert rendered.width > 0
    assert rendered.height > 0


def test_bundled_runtime_font_path_is_not_a_local_full_font() -> None:
    """统一字体 loader 不应再指向被删除的完整字体副本。"""

    assert fonts_module.BUNDLED_FONT_PATH is None


@pytest.mark.asyncio
async def test_help_without_snapshot_uses_placeholders_for_deleted_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """无 snapshot 时帮助卡不应因外置背景或字体不存在而抛 FileNotFoundError。"""

    async def fake_render(*_: object, **__: object) -> bytes:
        return b"jpeg"

    missing = tmp_path / "missing"
    monkeypatch.setattr(help_module, "_load_help_data", dict)
    monkeypatch.setattr(help_module._RENDERER, "render", fake_render)
    for name in (
        "BACKGROUND_PATH",
        "HELP_BANNER_PATH",
        "HELP_CAG_PATH",
        "HELP_FOOTER_PATH",
        "HELP_ITEM_PATH",
        "PLUGIN_ICON_PATH",
        "HELP_FONT_PATH",
    ):
        monkeypatch.setattr(help_module, name, missing)

    assert await help_module.get_help(prefix="", asset_resolver=None) == b"jpeg"
