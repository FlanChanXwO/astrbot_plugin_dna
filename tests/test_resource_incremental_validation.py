"""使用本地 Git 仓库验证资源增量校验，不访问网络。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from src.infrastructure.resources import generation as g
from src.infrastructure.resources.git import DEFAULT_RESOURCE_REMOTE, run_git


def _commit(root: Path, *, missing: dict[str, str] | None = None) -> None:
    hashes = {
        p.relative_to(root).as_posix(): g._sha256_file(p)
        for directory in ("alias", "data", "schemas", "images", "fonts")
        for p in (root / directory).rglob("*")
        if p.is_file()
    }
    hashes.update(missing or {})
    (root / "resource_manifest.json").write_text(
        g.ResourceManifest(
            format_version=2,
            required_dirs=("images", "fonts"),
            resource_version="test",
            file_hashes=hashes,
        ).model_dump_json(),
        encoding="utf-8",
    )
    run_git(("add", "."), root)
    run_git(("commit", "-m", "resources"), root)


@pytest.fixture
def resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    run_git(("init", "--initial-branch=main"), source)
    run_git(("config", "user.name", "Resource Test"), source)
    run_git(("config", "user.email", "test@example.invalid"), source)
    for directory in ("alias", "data", "schemas", "images", "fonts"):
        (source / directory).mkdir()
    for name in ("char_alias", "weapon_alias"):
        (source / "alias" / f"{name}.json").write_text("{}", encoding="utf-8")
    (source / "data/redeem_codes.json").write_text(
        '{"format_version":1,"data":[]}', encoding="utf-8"
    )
    (source / "schemas/redeem-codes.v1.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"type":"object","required":["format_version","data"]}',
        encoding="utf-8",
    )
    (source / "fonts/.keep").touch()
    for name in ("keep", "change"):
        Image.new("RGB", (8, 8), "red").save(source / f"images/{name}.png")
    _commit(source)

    def local_git(args, cwd=None):
        if args[0] in {"clone", "fetch"}:
            args = (
                "-c",
                f"url.{source.as_uri()}.insteadOf={DEFAULT_RESOURCE_REMOTE}",
                *args,
            )
        return run_git(args, cwd)

    custom_alias = tmp_path / "custom.json"

    def coordinator():
        return g.ResourceSnapshotCoordinator(
            tmp_path / "repository",
            generations_root=tmp_path / "generations",
            runner=local_git,
            custom_alias_path=custom_alias,
        )

    decoded: list[str] = []
    decode = g._validate_image_decodability

    def record(path: Path) -> None:
        decoded.append(path.name)
        decode(path)

    monkeypatch.setattr(g, "_validate_image_decodability", record)
    return source, coordinator, decoded, custom_alias


def test_unchanged_sync_reuses_decode_after_restart_and_refreshes_aliases(resources):
    _source, coordinator, decoded, custom_alias = resources
    first = coordinator().sync_resources()
    assert sorted(decoded) == ["change.png", "keep.png"]
    decoded.clear()
    custom_alias.write_text('{"角色甲":["小甲"]}', encoding="utf-8")
    restarted = coordinator()
    restarted.restore_current()

    result = restarted.sync_resources()

    assert result.action == "unchanged"
    assert result.commit_sha == first.commit_sha
    assert decoded == []
    assert (
        restarted.current_snapshot.encyclopedia_resources.aliases.resolve_char("小甲")
        == "角色甲"
    )


def test_new_generation_decodes_only_new_and_changed_images(resources):
    source, coordinator, decoded, _custom = resources
    store = coordinator()
    first = store.sync_resources()
    decoded.clear()
    Image.new("RGB", (8, 8), "blue").save(source / "images/change.png")
    Image.new("RGB", (8, 8), "green").save(source / "images/new.png")
    _commit(source)

    updated = store.sync_resources()

    assert sorted(decoded) == ["change.png", "new.png"]
    assert updated.action == "updated"
    assert not first.generation_root.exists()
    assert updated.generation_root == store.current_snapshot.root
    assert (updated.generation_root / "images/new.png").is_file()

    decoded.clear()
    (source / "data/redeem_codes.json").write_text(
        '{"format_version":1,"data":[{"code":"NEW"}]}', encoding="utf-8"
    )
    _commit(source)
    store.sync_resources()
    assert decoded == []

    # 未在新 manifest 声明摘要的图片，仍需实际解码。
    decoded.clear()
    manifest = g.ResourceManifest.load(source / "resource_manifest.json")
    del manifest.file_hashes["images/keep.png"]
    (source / "resource_manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    run_git(("add", "."), source)
    run_git(("commit", "-m", "unhashed image"), source)
    store.sync_resources()
    assert decoded == ["keep.png"]


@pytest.mark.parametrize("damage", ["image", "missing_digest"])
def test_damaged_current_is_rebuilt_without_trusting_cached_decode(resources, damage):
    _source, coordinator, decoded, _custom = resources
    store = coordinator()
    first = store.sync_resources()
    decoded.clear()
    if damage == "image":
        (first.generation_root / "images/keep.png").write_bytes(b"broken")
    else:
        pointer = json.loads(store.state_path.read_text())
        del pointer["content_sha256"]
        store.state_path.write_text(json.dumps(pointer), encoding="utf-8")
        store = coordinator()

    repaired = store.sync_resources()

    assert repaired.action == ("updated" if damage == "image" else "unchanged")
    assert json.loads(store.state_path.read_text())["content_sha256"]
    assert sorted(decoded) == ["change.png", "keep.png"]
    with Image.open(repaired.generation_root / "images/keep.png") as image:
        image.load()
    assert store.current_snapshot is not None


def test_invalid_new_image_does_not_publish_or_advance_repository(resources):
    source, coordinator, decoded, _custom = resources
    store = coordinator()
    first = store.sync_resources()
    decoded.clear()
    (source / "images/broken.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)
    _commit(source)

    with pytest.raises(g.ResourceGenerationError, match="不可解码"):
        store.sync_resources()

    assert store.current_snapshot.commit_sha == first.commit_sha
    assert (
        run_git(("rev-parse", "HEAD"), store.repository).stdout.strip()
        == first.commit_sha
    )
    assert json.loads(store.state_path.read_text())["generation"] == first.commit_sha


def test_repair_waits_for_existing_generation_lease(resources, monkeypatch):
    _source, coordinator, _decoded, _custom = resources
    store = coordinator()
    first = store.sync_resources()
    repairing = Event()
    begin_repair = store._begin_generation_repair

    def observed_repair(commit_sha):
        repairing.set()
        begin_repair(commit_sha)

    monkeypatch.setattr(store, "_begin_generation_repair", observed_repair)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.acquire() as leased:
            image = leased.root / "images/keep.png"
            image.write_bytes(b"broken")
            future = pool.submit(store.sync_resources)
            assert repairing.wait(5)
            assert not future.done()
            assert image.read_bytes() == b"broken"
        result = future.result(timeout=5)

    assert result.commit_sha == first.commit_sha
    with Image.open(result.generation_root / "images/keep.png") as image:
        image.load()


def test_previously_absent_optional_image_is_not_a_verified_cache_entry(resources):
    source, coordinator, decoded, _custom = resources
    broken = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4
    optional = source / "images/optional.png"
    optional.write_bytes(broken)
    digest = g._sha256_file(optional)
    optional.unlink()
    _commit(source, missing={"images/optional.png": digest})
    store = coordinator()
    store.sync_resources()
    decoded.clear()
    optional.write_bytes(broken)
    _commit(source)

    with pytest.raises(g.ResourceGenerationError, match="不可解码"):
        store.sync_resources()
    assert "optional.png" in decoded


@pytest.mark.parametrize("damage", ["content", "required_directory", "symlink"])
def test_digest_reuse_preserves_integrity_and_layout_checks(resources, damage):
    _source, coordinator, _decoded, _custom = resources
    snapshot = coordinator().sync_resources()
    root = snapshot.generation_root
    # 空目录不参与内容摘要，但 required_dirs 仍必须检查。
    manifest = g.ResourceManifest.load(root / "resource_manifest.json")
    (root / "empty").mkdir()
    manifest.required_dirs += ("empty",)
    (root / "resource_manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    trusted = g.ResourceGenerationValidator().validate(root, snapshot.commit_sha)
    if damage == "content":
        (root / "images/keep.png").write_bytes(b"changed")
    elif damage == "required_directory":
        (root / "empty").rmdir()
    else:
        image = root / "images/keep.png"
        target = root.parent / "external.png"
        image.rename(target)
        image.symlink_to(target)

    with pytest.raises(g.ResourceGenerationError):
        g.ResourceGenerationValidator().validate(
            root, snapshot.commit_sha, expected_content_sha256=trusted.content_sha256
        )
