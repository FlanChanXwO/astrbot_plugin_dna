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
