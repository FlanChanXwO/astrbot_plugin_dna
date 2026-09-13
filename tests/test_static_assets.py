from pathlib import Path

from src.infrastructure.rendering.static_assets import StaticAssetResolver


def test_static_asset_resolver_prefers_snapshot_then_bootstrap(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "fonts").mkdir(parents=True)
    (snapshot / "fonts" / "dna_fonts.ttf").write_bytes(b"font")
    bootstrap = tmp_path / "bootstrap.ttf"
    bootstrap.write_bytes(b"bootstrap")

    resolver = StaticAssetResolver(
        snapshot_root=snapshot,
        bootstrap_allowlist={"font.dna": bootstrap},
        asset_paths={"font.dna": "fonts/dna_fonts.ttf"},
    )
    resolved = resolver.resolve("font.dna")
    assert resolved.path == snapshot / "fonts" / "dna_fonts.ttf"
    assert resolved.source == "verified_snapshot"
    assert not resolved.incomplete

    (snapshot / "fonts" / "dna_fonts.ttf").unlink()
    resolved = resolver.resolve("font.dna")
    assert resolved.path == bootstrap
    assert resolved.source == "bootstrap"
    assert not resolved.incomplete


def test_static_asset_resolver_marks_missing_and_rejects_escape(tmp_path: Path) -> None:
    resolver = StaticAssetResolver(snapshot_root=tmp_path / "snapshot")
    missing = resolver.resolve("texture.missing")
    assert missing.path is None
    assert missing.source == "none"
    assert missing.incomplete

    resolver = StaticAssetResolver(
        snapshot_root=tmp_path,
        asset_paths={"bad": "../outside"},
    )
    try:
        resolver.resolve("bad")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe static asset path must be rejected")


def test_resolve_relative_prefers_snapshot_then_common_bootstrap(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "textures" / "role").mkdir(parents=True)
    (snapshot / "textures" / "role" / "info_bar.png").write_bytes(b"png")
    bootstrap_dir = tmp_path / "texture2d"
    bootstrap_dir.mkdir()
    (bootstrap_dir / "bg1.jpg").write_bytes(b"jpg")

    resolver = StaticAssetResolver(
        snapshot_root=snapshot,
        bootstrap_texture_dir=bootstrap_dir,
        bootstrap_relative_allowlist={"textures/common/bg1.jpg"},
    )
    resolved = resolver.resolve_relative("textures/role/info_bar.png")
    assert resolved.path == snapshot / "textures" / "role" / "info_bar.png"
    assert resolved.source == "verified_snapshot"
    assert not resolved.incomplete

    resolved = resolver.resolve_relative("textures/common/bg1.jpg")
    assert resolved.path == bootstrap_dir / "bg1.jpg"
    assert resolved.source == "bootstrap"
    assert not resolved.incomplete

    # 未列入显式 allowlist 的 common 路径不得隐式回退本地 bootstrap。
    resolved = resolver.resolve_relative("textures/common/not_allowlisted.jpg")
    assert resolved.path is None
    assert resolved.incomplete


def test_resolve_relative_marks_missing_and_rejects_escape(tmp_path: Path) -> None:
    resolver = StaticAssetResolver(snapshot_root=tmp_path / "snapshot")
    missing = resolver.resolve_relative("fonts/dna_fonts.ttf")
    assert missing.path is None
    assert missing.source == "none"
    assert missing.incomplete

    for unsafe in ("../outside.png", "textures/../..//escape.png", "/abs.png"):
        try:
            resolver.resolve_relative(unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe relative path must be rejected: {unsafe}")


def test_pinned_resolver_keeps_snapshot_root_fixed(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root in (root_a, root_b):
        (root / "fonts").mkdir(parents=True)
    (root_a / "fonts" / "dna_fonts.ttf").write_bytes(b"a")

    class _Snapshot:
        commit_sha = "b-commit"

    class _Coordinator:
        def __init__(self) -> None:
            self.current_snapshot = None

    coordinator = _Coordinator()
    resolver = StaticAssetResolver(coordinator=coordinator)
    pinned = resolver.pinned(root_a, generation_id="a-commit")
    # 协调器此后切换 generation 也不影响已固定的解析器。
    coordinator.current_snapshot = _Snapshot()
    resolved = pinned.resolve_relative("fonts/dna_fonts.ttf")
    assert resolved.path == root_a / "fonts" / "dna_fonts.ttf"
    assert resolved.source == "verified_snapshot"
    assert pinned.generation_id == "a-commit"
    assert resolver.generation_id == "b-commit"


def test_static_helpers_fallback_and_record(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "textures" / "sign").mkdir(parents=True)
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(buffer, format="PNG")
    (snapshot / "textures" / "sign" / "bar.png").write_bytes(buffer.getvalue())

    from src.infrastructure.rendering.static_assets import (
        static_image_data_uri,
        static_open_image,
        static_record,
    )

    resolver = StaticAssetResolver(snapshot_root=snapshot)
    uri, asset = static_image_data_uri(
        resolver, "textures/sign/bar.png", label="签到"
    )
    assert uri.startswith("data:image/png;base64,")
    assert asset.source == "verified_snapshot"
    assert static_record("texture.sign.bar", asset).get("incomplete") == "false"

    uri, asset = static_image_data_uri(
        resolver, "textures/sign/missing.png", label="签到"
    )
    assert uri.startswith("data:image/png;base64,")
    assert asset.incomplete
    assert static_record("texture.sign.missing", asset).get("incomplete") == "true"

    image = static_open_image(
        resolver, "textures/sign/bar.png", size=(4, 4), label="签到"
    )
    assert image.size == (4, 4)
    assert isinstance(image, Image.Image)

    placeholder = static_open_image(
        resolver, "textures/sign/none.png", size=(4, 4), label="签到"
    )
    assert placeholder.size == (4, 4)


def test_resolve_supports_bootstrap_only_keys(tmp_path: Path) -> None:
    """没有 snapshot 映射的 key 也必须能进入 bootstrap 检查。"""

    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    resolver = StaticAssetResolver(bootstrap_allowlist={"texture.help.logo": logo})
    resolved = resolver.resolve("texture.help.logo")
    assert resolved.path == logo
    assert resolved.source == "bootstrap"
    assert not resolved.incomplete


def test_resolve_bootstrap_dir_icons(tmp_path: Path) -> None:
    """帮助命令图标经 bootstrap 目录解析，且拒绝路径逃逸。"""

    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    (icon_dir / "签到日历.png").write_bytes(b"png")
    resolver = StaticAssetResolver(bootstrap_dirs={"texture.help.icon": icon_dir})

    resolved = resolver.resolve("texture.help.icon:签到日历.png")
    assert resolved.path == icon_dir / "签到日历.png"
    assert resolved.source == "bootstrap"

    missing = resolver.resolve("texture.help.icon:不存在.png")
    assert missing.path is None
    assert missing.incomplete

    escaped = resolver.resolve("texture.help.icon:../escape.png")
    assert escaped.path is None
    assert escaped.incomplete
