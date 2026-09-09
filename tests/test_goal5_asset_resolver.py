"""Goal 5 Task 04-05：统一运行期资源解析与降级契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.bootstrap import _BOOTSTRAP_ALLOWLIST, _SNAPSHOT_ASSET_PATHS
from src.infrastructure.resources import (
    ResourceGenerationError,
    ResourceSnapshotCoordinator,
)
from src.infrastructure.resources.resolver import RuntimeAssetResolver


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _resolver(
    *,
    snapshot_root: Path | None = None,
    snapshot_assets: dict[str, str] | None = None,
    bootstrap_allowlist: dict[str, Path] | None = None,
) -> RuntimeAssetResolver:
    return RuntimeAssetResolver(
        snapshot_root=snapshot_root,
        snapshot_assets=snapshot_assets or {},
        bootstrap_allowlist=bootstrap_allowlist or {},
    )


def test_renderer_texture_keys_map_to_real_snapshot_files(tmp_path: Path) -> None:
    """卡片纹理 key 必须映射到资源仓库中的具体、可读取文件。"""

    expected = {
        "texture:stamina:bg": "textures/stamina/bg/bg6.png",
        "texture.mh.card": "textures/mh/card.png",
        "texture.ann.list": "textures/ann/dna_official_avatar.jpeg",
        "texture.ann.detail": "textures/ann/dna_official_avatar.jpeg",
        "texture.sign.background": "textures/sign/role_bg.png",
        "texture.sign.bar": "textures/sign/bar.png",
        "texture.sign.item_BG": "textures/sign/item_BG.png",
        "texture.sign.green": "textures/sign/green.png",
        "texture.sign.red": "textures/sign/red.png",
        "texture.sign.line": "textures/sign/line.png",
        "texture.help.background": "textures/help/bg.jpg",
        "texture.help.banner": "textures/help/banner_bg.jpg",
        "texture.help.cag": "textures/help/cag_bg.png",
        "texture.help.item": "textures/help/item.png",
        "texture.common.footer": "textures/common/footer.png",
    }
    root = tmp_path / "generation"
    for relative in expected.values():
        _write(root / relative, relative.encode())

    resolver = _resolver(
        snapshot_root=root,
        snapshot_assets=_SNAPSHOT_ASSET_PATHS,
    )

    for logical_key, relative in expected.items():
        resolved = resolver.resolve(logical_key)
        assert resolved.path == root / relative
        assert resolved.source == "verified_snapshot"
        assert resolved.status == "provided"


def test_verified_snapshot_wins_over_bootstrap_for_font_and_texture(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "resource-generations" / ("a" * 40)
    snapshot_font = _write(snapshot_root / "fonts" / "dna_fonts.ttf", b"snapshot-font")
    snapshot_texture = _write(
        snapshot_root / "images" / "common" / "card.png",
        b"snapshot-texture",
    )
    bootstrap_font = _write(tmp_path / "bootstrap" / "font.ttf", b"bootstrap-font")
    bootstrap_texture = _write(
        tmp_path / "bootstrap" / "card.png",
        b"bootstrap-texture",
    )

    resolver = _resolver(
        snapshot_root=snapshot_root,
        snapshot_assets={
            "font.primary_ttf": "fonts/dna_fonts.ttf",
            "texture.common.card": "images/common/card.png",
        },
        bootstrap_allowlist={
            "font.primary_ttf": bootstrap_font,
            "texture.common.card": bootstrap_texture,
        },
    )

    font = resolver.resolve("font.primary_ttf")
    texture = resolver.resolve("texture.common.card")

    assert font.path == snapshot_font
    assert font.source == "verified_snapshot"
    assert font.status == "provided"
    assert font.incomplete is False
    assert texture.path == snapshot_texture
    assert texture.source == "verified_snapshot"
    assert texture.status == "provided"
    assert texture.incomplete is False


def test_role_weapon_and_panel_logical_keys_use_verified_snapshot(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "resource-generations" / ("b" * 40)
    assets = {
        "role_avatar": _write(
            snapshot_root / "images" / "role_avatar" / "100.png",
            b"role-avatar",
        ),
        "role_paint": _write(
            snapshot_root / "images" / "role_paint" / "100.png",
            b"role-paint",
        ),
        "weapon": _write(
            snapshot_root / "images" / "weapon" / "200.png",
            b"weapon",
        ),
        "panel": _write(snapshot_root / "panel" / "100.png", b"panel"),
    }
    resolver = _resolver(
        snapshot_root=snapshot_root,
        snapshot_assets={
            "image:role_avatar:100": "images/role_avatar/100.png",
            "image:role_paint:100": "images/role_paint/100.png",
            "image:weapon:200": "images/weapon/200.png",
            "panel:original:100": "panel/100.png",
        },
    )

    for logical_key, expected_path in assets.items():
        key = {
            "role_avatar": "image:role_avatar:100",
            "role_paint": "image:role_paint:100",
            "weapon": "image:weapon:200",
            "panel": "panel:original:100",
        }[logical_key]
        resolved = resolver.resolve(key)
        assert resolved.path == expected_path
        assert resolved.source == "verified_snapshot"
        assert resolved.incomplete is False


def test_missing_snapshot_uses_only_explicit_bootstrap_allowlist(
    tmp_path: Path,
) -> None:
    legacy_tree = _write(
        tmp_path / "legacy-cache" / "textures" / "common" / "card.png",
        b"legacy-cache-must-not-be-read",
    )
    bootstrap_font = _write(tmp_path / "bootstrap" / "help-subset.ttf", b"small-font")
    resolver = _resolver(
        snapshot_root=None,
        bootstrap_allowlist={"font.help": bootstrap_font},
    )

    bootstrap = resolver.resolve("font.help")
    missing = resolver.resolve("texture.common.card")

    assert legacy_tree.is_file()
    assert bootstrap.path == bootstrap_font
    assert bootstrap.source == "bootstrap"
    assert bootstrap.status == "fallback"
    assert bootstrap.incomplete is False
    assert missing.path is None
    assert missing.source == "none"
    assert missing.status == "missing"
    assert missing.incomplete is True


def test_snapshot_file_missing_falls_back_to_bootstrap_not_candidate(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "resource-generations" / ("c" * 40)
    candidate_path = _write(
        tmp_path / ".candidate-unverified" / "fonts" / "dna_fonts.ttf",
        b"candidate-must-not-be-read",
    )
    cache_path = _write(
        tmp_path / "resources-cache" / "fonts" / "dna_fonts.ttf",
        b"cache-must-not-be-read",
    )
    bootstrap_path = _write(tmp_path / "bootstrap" / "dna_fonts.ttf", b"bootstrap")
    resolver = _resolver(
        snapshot_root=snapshot_root,
        snapshot_assets={"font.primary_ttf": "fonts/dna_fonts.ttf"},
        bootstrap_allowlist={"font.primary_ttf": bootstrap_path},
    )

    resolved = resolver.resolve("font.primary_ttf")

    assert candidate_path.is_file()
    assert cache_path.is_file()
    assert resolved.path == bootstrap_path
    assert resolved.source == "bootstrap"
    assert resolved.status == "fallback"
    assert resolved.incomplete is True


@pytest.mark.parametrize(
    "relative_path",
    ["/outside/font.ttf", "../outside/font.ttf", "fonts\\\\font.ttf"],
)
def test_snapshot_asset_mapping_rejects_unsafe_paths(
    relative_path: str,
) -> None:
    """snapshot 映射只能声明 generation 内的 POSIX 相对路径。"""

    with pytest.raises(ValueError, match="snapshot 资源路径"):
        _resolver(snapshot_assets={"font.primary_ttf": relative_path})


def test_snapshot_resolver_rejects_symlink_root_and_asset(tmp_path: Path) -> None:
    """解析器不能跟随 generation 根或文件符号链接读取外部内容。"""

    real_root = tmp_path / "real-generation"
    snapshot_asset = _write(real_root / "fonts" / "dna_fonts.ttf", b"font")
    outside = _write(tmp_path / "outside.ttf", b"outside")
    snapshot_asset.unlink()
    snapshot_asset.symlink_to(outside)
    snapshot_root_link = tmp_path / "snapshot-link"
    snapshot_root_link.symlink_to(real_root, target_is_directory=True)

    root_resolver = _resolver(
        snapshot_root=snapshot_root_link,
        snapshot_assets={"font.primary_ttf": "fonts/dna_fonts.ttf"},
    )
    assert root_resolver.resolve("font.primary_ttf").path is None

    asset_resolver = _resolver(
        snapshot_root=real_root,
        snapshot_assets={"font.primary_ttf": "fonts/dna_fonts.ttf"},
    )
    assert asset_resolver.resolve("font.primary_ttf").path is None


def test_unresolved_asset_exposes_none_state_for_renderer_placeholder(
    tmp_path: Path,
) -> None:
    resolver = _resolver(snapshot_root=None)

    resolved = resolver.resolve("texture.detail.missing")

    assert resolved.path is None
    assert resolved.source == "none"
    assert resolved.status == "missing"
    assert resolved.incomplete is True


def test_empty_snapshot_keeps_existing_coordinator_context_contract(
    tmp_path: Path,
) -> None:
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource-generations",
    )
    assert coordinator.initialize() is None

    with pytest.raises(ResourceGenerationError):
        coordinator.acquire()
    with coordinator.optional_lease() as snapshot:
        assert snapshot is None
    with coordinator.bind_resource("player_resources") as resources:
        assert resources is None

    renderer = object()
    with coordinator.bind_renderer(renderer, "player_resources") as bound:
        assert bound is renderer


def test_bind_resolver_uses_the_current_snapshot_lease(tmp_path: Path) -> None:
    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource-generations",
    )
    assert coordinator.initialize() is None

    with coordinator.bind_resolver(
        lambda snapshot: _resolver(
            snapshot_root=None if snapshot is None else snapshot.root,
        )
    ) as resolver:
        resolved = resolver.resolve("font.primary_ttf")

    assert resolved.path is None
    assert resolved.source == "none"
    assert resolved.status == "missing"
    assert resolved.incomplete is True


@pytest.mark.asyncio
async def test_bootstrap_uses_empty_resource_views_without_verified_snapshot(
    tmp_path: Path,
) -> None:
    resource_root = tmp_path / "resources"
    _write(resource_root / "fonts" / "dna_fonts.ttf", b"unverified-cache-font")

    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    player_resources = runtime.services["player_resources"]
    encyclopedia_resources = runtime.services["encyclopedia_resources"]
    assert player_resources.root is None
    assert encyclopedia_resources.font_path is None

    with runtime.services["bind_resource_resolver"]() as resolver:
        bootstrap = resolver.resolve("texture.common.number.0")
    assert bootstrap.source == "bootstrap"
    assert bootstrap.status == "fallback"
    assert bootstrap.incomplete is True


def test_help_bootstrap_assets_are_complete_without_verified_snapshot() -> None:
    resolver = _resolver(
        snapshot_assets=_SNAPSHOT_ASSET_PATHS,
        bootstrap_allowlist=_BOOTSTRAP_ALLOWLIST,
    )

    logo = resolver.resolve("texture.help.logo")
    icon = resolver.resolve("texture.help.icon:日常.png")
    unknown_icon = resolver.resolve("texture.help.icon:不存在.png")
    font = resolver.resolve("font.help")

    for asset in (logo, icon):
        assert asset.path is not None
        assert asset.path.is_file()
        assert asset.source == "bootstrap"
        assert asset.status == "fallback"
        assert asset.incomplete is False
    assert unknown_icon.path is None
    assert unknown_icon.source == "none"
    assert unknown_icon.status == "missing"
    assert unknown_icon.incomplete is True
    assert font.path is None
    assert font.source == "none"
    assert font.status == "missing"
    assert font.incomplete is True
