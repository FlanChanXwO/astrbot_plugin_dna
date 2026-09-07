"""Goal 3 Task 17：资源 generation、候选校验和运行期快照契约。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from builtins import ExceptionGroup
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PIL import Image

from src.bootstrap import build_runtime
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.resources import (
    DEFAULT_RESOURCE_REMOTE,
    GitCommandError,
    GitCommandResult,
    ResourceGenerationError,
    ResourceGenerationValidator,
    ResourceSnapshotCoordinator,
    run_git,
)
from src.infrastructure.resources.manifest import RUNTIME_RESOURCE_DIRECTORIES
from src.modules.operations.resource_service import ResourceUpdateService


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _operation(args: tuple[str, ...]) -> str:
    return args[2] if args[:1] == ("-c",) else args[0]


def _write_resources(root: Path, version: str, *, broken: bool = False) -> None:
    required_dirs = (*RUNTIME_RESOURCE_DIRECTORIES, "data", "schemas")
    for relative in required_dirs:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".keep").write_text("fixture\n", encoding="utf-8")
    (root / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": list(required_dirs),
                "resource_version": version,
            }
        ),
        encoding="utf-8",
    )
    (root / "alias" / "char_alias.json").write_text(
        json.dumps({"角色甲": ["角色甲", "小甲"]}),
        encoding="utf-8",
    )
    (root / "alias" / "weapon_alias.json").write_text(
        json.dumps({"武器甲": ["武器甲"]}),
        encoding="utf-8",
    )
    (root / "data" / "redeem_codes.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "data": [{"code": "CODE-" + version}],
            }
            if not broken
            else {"format_version": 1, "data": [{"code": ""}]}
        ),
        encoding="utf-8",
    )
    (root / "schemas" / "redeem-codes.v1.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["format_version", "data"],
            }
        ),
        encoding="utf-8",
    )
    image_path = root / "images" / "role_avatar" / "1.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if broken:
        image_path.write_bytes(b"not-a-png")
    else:
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(image_path, format="PNG")
        wiki_path = root / "wiki" / "role" / "角色甲.png"
        Image.new("RGBA", (2, 2), (0, 255, 0, 255)).save(wiki_path, format="PNG")
    (root / "fonts" / "dna_fonts.ttf").write_bytes(b"\x00\x01\x00\x00fixture")


def _commit_main(source: Path, version: str, *, broken: bool = False) -> None:
    _write_resources(source, version, broken=broken)
    _git("add", ".", cwd=source)
    _git("commit", "-m", version, cwd=source)
    _git("push", "fixture", "main", cwd=source)


class LocalBareRunner:
    """把 canonical GitHub URL 映射到本地 bare fixture，不改产品调用参数。"""

    def __init__(self, bare: Path, target: Path) -> None:
        self.bare = bare
        self.target = target
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        args: tuple[str, ...],
        cwd: Path | None = None,
    ) -> GitCommandResult:
        self.calls.append(args)
        operation = _operation(args)
        if operation in {"clone", "fetch", "pull"}:
            mapping = f"url.{self.bare.as_uri()}.insteadOf={DEFAULT_RESOURCE_REMOTE}"
            result = run_git(("-c", mapping, *args), cwd)
        else:
            result = run_git(args, cwd)
        if operation == "clone":
            _git(
                "remote", "set-url", "origin", DEFAULT_RESOURCE_REMOTE, cwd=self.target
            )
        return result


def _fixture(tmp_path: Path) -> tuple[Path, Path, LocalBareRunner]:
    bare = tmp_path / "remote.git"
    source = tmp_path / "source"
    source.mkdir()
    _git("init", "--bare", str(bare), cwd=tmp_path)
    _git("init", "--initial-branch=main", str(source), cwd=tmp_path)
    _git("config", "user.name", "Task 17 Fixture", cwd=source)
    _git("config", "user.email", "task17@example.invalid", cwd=source)
    _git("remote", "add", "fixture", bare.as_uri(), cwd=source)
    _commit_main(source, "v1")
    _git("checkout", "-b", "feature", cwd=source)
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git("add", "feature.txt", cwd=source)
    _git("commit", "-m", "feature", cwd=source)
    _git("tag", "feature-tag", cwd=source)
    _git("checkout", "main", cwd=source)
    _git("push", "fixture", "feature", "--tags", cwd=source)
    target = tmp_path / "resources"
    return source, target, LocalBareRunner(bare, target)


def _coordinator(
    tmp_path: Path, runner: LocalBareRunner
) -> ResourceSnapshotCoordinator:
    return ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
    )


def test_sync_archives_fetch_head_and_publishes_only_valid_main_generation(
    tmp_path: Path,
) -> None:
    source, target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    published = []
    coordinator.subscribe(published.append)

    result = coordinator.synchronize()
    snapshot = coordinator.current_snapshot

    assert snapshot is not None
    assert result.commit_sha == snapshot.commit_sha
    assert result.content_sha256 == snapshot.content_sha256
    assert len(snapshot.content_sha256) == 64
    assert snapshot.root == tmp_path / "resource_generations" / result.commit_sha
    assert snapshot.player_resources.root == snapshot.root
    assert all(
        path.is_relative_to(snapshot.root) and path.is_file()
        for path in snapshot.encyclopedia_resources.wiki_assets.values()
    )
    assert (snapshot.root / "main").exists() is False
    assert not (snapshot.root / "feature.txt").exists()
    assert (snapshot.root / "resource_manifest.json").is_file()
    assert (
        _git("remote", "get-url", "origin", cwd=target).strip()
        == DEFAULT_RESOURCE_REMOTE
    )
    assert _git("branch", "--show-current", cwd=target).strip() == "main"
    assert _git(
        "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin", cwd=target
    ).splitlines() == ["origin/main"]
    assert _git("tag", cwd=target).strip() == ""
    assert any(
        _operation(call) == "archive" and "FETCH_HEAD" in call for call in runner.calls
    )
    state = json.loads(coordinator.state_path.read_text(encoding="utf-8"))
    assert state["generation"] == result.commit_sha
    assert state["content_sha256"] == result.content_sha256
    assert [item.commit_sha for item in published] == [result.commit_sha]
    assert source.exists()


def test_sync_resources_is_canonical_sync_entrypoint(tmp_path: Path) -> None:
    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)

    result = coordinator.sync_resources()

    assert result.commit_sha
    assert coordinator.current_snapshot is not None
    assert coordinator.current_snapshot.commit_sha == result.commit_sha


def test_sync_same_remote_commit_returns_unchanged_without_rebuilding_generation(
    tmp_path: Path,
) -> None:
    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    calls_before = len(runner.calls)

    second = coordinator.synchronize()
    new_calls = runner.calls[calls_before:]

    assert second.action == "unchanged"
    assert second.commit_sha == first.commit_sha
    assert second.generation_root == first.generation_root
    assert not any(_operation(call) == "archive" for call in new_calls)
    assert not any(_operation(call) == "merge" for call in new_calls)


def test_sync_same_remote_commit_after_restart_validates_current_generation(
    tmp_path: Path,
) -> None:
    """重启后的同 commit 快路径也必须验证已发布 generation 的完整性。"""

    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    assert first.generation_root is not None

    alias_path = first.generation_root / "alias" / "char_alias.json"
    alias_path.write_text('{"角色甲": ["已篡改"]}', encoding="utf-8")

    restarted = _coordinator(tmp_path, runner)
    assert restarted.load_current() is not None

    with pytest.raises(ResourceGenerationError, match="内容哈希不匹配"):
        restarted.validate_current()

    repaired = restarted.synchronize()
    assert repaired.commit_sha == first.commit_sha
    assert restarted.current_snapshot is not None
    assert restarted.current_snapshot.commit_sha == first.commit_sha


def test_sync_reports_validation_and_cleanup_failures_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, _target, runner = _fixture(tmp_path)

    class FailingValidator:
        def validate(self, root: Path, commit_sha: str):
            del root, commit_sha
            raise ResourceGenerationError("candidate invalid")

    coordinator = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
        validator=FailingValidator(),
    )

    def fail_cleanup(_path: Path) -> None:
        raise OSError("cleanup failed")

    monkeypatch.setattr(coordinator, "_remove_generation", fail_cleanup)

    with pytest.raises(ExceptionGroup) as caught:
        coordinator.synchronize()

    messages = {str(error) for error in caught.value.exceptions}
    assert "candidate invalid" in messages
    assert "cleanup failed" in messages


def test_invalid_candidate_keeps_last_verified_snapshot_and_cleans_temp_files(
    tmp_path: Path,
) -> None:
    source, target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    old = coordinator.current_snapshot
    assert old is not None
    old_checkout = _git("rev-parse", "HEAD", cwd=target).strip()

    _git("checkout", "main", cwd=source)
    _commit_main(source, "broken", broken=True)

    with pytest.raises(ResourceGenerationError, match="资源候选 generation 校验失败"):
        coordinator.synchronize()

    current = coordinator.current_snapshot
    assert current is old
    assert current.commit_sha == first.commit_sha
    assert old.root.is_dir()
    assert _git("rev-parse", "HEAD", cwd=target).strip() == old_checkout
    assert (
        json.loads(coordinator.state_path.read_text(encoding="utf-8"))["generation"]
        == first.commit_sha
    )
    assert not any(
        path.name.startswith((".candidate-", ".archive-"))
        for path in coordinator.generations_root.iterdir()
    )


def test_git_failure_keeps_last_verified_snapshot(tmp_path: Path) -> None:
    _source, _target, healthy_runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, healthy_runner)
    first = coordinator.synchronize()

    class FailingRunner(LocalBareRunner):
        def __call__(self, args: tuple[str, ...], cwd: Path | None = None):
            if _operation(args) in {"pull", "fetch"}:
                raise GitCommandError(_operation(args), "mirror unavailable")
            return super().__call__(args, cwd)

    restarted = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=FailingRunner(healthy_runner.bare, healthy_runner.target),
    )
    restarted.initialize()
    with pytest.raises(GitCommandError, match="mirror unavailable"):
        restarted.synchronize()

    assert restarted.current_snapshot is not None
    assert restarted.current_snapshot.commit_sha == first.commit_sha
    assert restarted.current_snapshot.root.is_dir()


def test_lease_keeps_old_generation_until_all_readers_release(tmp_path: Path) -> None:
    source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    lease_one = coordinator.acquire()
    lease_two = coordinator.acquire()
    old_root = lease_one.root

    _git("checkout", "main", cwd=source)
    _commit_main(source, "v2")
    second = coordinator.synchronize()

    assert second.commit_sha != first.commit_sha
    assert coordinator.current_snapshot is not None
    assert coordinator.current_snapshot.commit_sha == second.commit_sha
    assert old_root.is_dir()

    lease_one.release()
    assert old_root.is_dir()
    lease_two.release()
    assert not old_root.exists()


def test_renderer_binding_pins_generation_for_render_duration(tmp_path: Path) -> None:
    source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    old_root = first.generation_root
    assert old_root is not None
    first_snapshot = coordinator.current_snapshot
    assert first_snapshot is not None

    class Renderer:
        resources = None

    renderer = Renderer()
    with coordinator.bind_renderer(renderer, "player_resources") as bound:
        assert bound is not renderer
        assert bound.resources is coordinator.current_snapshot.player_resources

        _git("checkout", "main", cwd=source)
        _commit_main(source, "v2")
        coordinator.synchronize()

        assert bound.resources is first_snapshot.player_resources

    assert not old_root.exists()


def test_resource_binding_does_not_mask_consumer_attribute_errors(
    tmp_path: Path,
) -> None:
    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    coordinator.synchronize()

    with (
        pytest.raises(AttributeError, match="consumer failure"),
        coordinator.bind_resource("player_resources"),
    ):
        raise AttributeError("consumer failure")


def test_validator_rejects_duplicate_alias_under_one_canonical_name(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    (candidate / "alias" / "char_alias.json").write_text(
        json.dumps({"角色甲": ["角色甲", "角色甲"]}),
        encoding="utf-8",
    )

    with pytest.raises(ResourceGenerationError, match="资源候选别名重复"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_rejects_containment_ambiguous_aliases(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    (candidate / "alias" / "char_alias.json").write_text(
        json.dumps(
            {
                "角色甲": ["短名"],
                "角色乙": ["短名后缀"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResourceGenerationError, match="资源候选别名存在歧义"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_rejects_canonical_alias_collision(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    (candidate / "alias" / "char_alias.json").write_text(
        json.dumps(
            {
                "角色甲": ["仅甲"],
                "角色乙": ["角色甲"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResourceGenerationError, match="资源候选别名存在歧义"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_rejects_schema_without_draft_identifier(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    (candidate / "schemas" / "redeem-codes.v1.schema.json").write_text(
        json.dumps({"type": "object", "required": ["format_version", "data"]}),
        encoding="utf-8",
    )

    with pytest.raises(ResourceGenerationError, match="资源候选兑换码 schema 格式错误"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_rejects_symlinked_resource_files(tmp_path: Path) -> None:
    """generation 内的资源文件不得通过符号链接读取 generation 外部内容。"""

    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    outside = tmp_path / "outside-alias.json"
    outside.write_text(json.dumps({"角色甲": ["外部别名"]}), encoding="utf-8")
    alias_path = candidate / "alias" / "char_alias.json"
    alias_path.unlink()
    alias_path.symlink_to(outside)

    with pytest.raises(ResourceGenerationError, match="资源候选不允许符号链接"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_handles_complete_binary_assets_without_path_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """候选校验读取文件头后仍能正常处理完整的图片和字体。"""

    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("候选头部校验不应读取完整文件")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    snapshot = ResourceGenerationValidator().validate(candidate, "a" * 40)

    assert snapshot.commit_sha == "a" * 40


def test_validator_rejects_truncated_image_after_valid_header(tmp_path: Path) -> None:
    """仅伪造图片文件头的候选不能通过完整解码校验。"""

    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    (candidate / "images" / "role_avatar" / "1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"truncated"
    )

    with pytest.raises(ResourceGenerationError, match="图片不可解码"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_validator_checks_optional_manifest_file_hashes(tmp_path: Path) -> None:
    """manifest 声明的文件哈希必须匹配候选内容。"""

    candidate = tmp_path / "candidate"
    _write_resources(candidate, "v1")
    alias_path = candidate / "alias" / "char_alias.json"
    manifest_path = candidate / "resource_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_hashes"] = {
        "alias/char_alias.json": hashlib.sha256(alias_path.read_bytes()).hexdigest()
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = ResourceGenerationValidator().validate(candidate, "a" * 40)
    assert (
        snapshot.manifest.file_hashes["alias/char_alias.json"]
        == manifest["file_hashes"]["alias/char_alias.json"]
    )

    alias_path.write_text('{"角色甲": ["被篡改"]}', encoding="utf-8")
    with pytest.raises(ResourceGenerationError, match="文件哈希不匹配"):
        ResourceGenerationValidator().validate(candidate, "a" * 40)


def test_initialize_rejects_tampered_content_hash_pointer(tmp_path: Path) -> None:
    """active pointer 中的内容哈希不匹配时不得恢复该 generation。"""

    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    coordinator.synchronize()
    state = json.loads(coordinator.state_path.read_text(encoding="utf-8"))
    state["content_sha256"] = "0" * 64
    coordinator.state_path.write_text(json.dumps(state), encoding="utf-8")

    restarted = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
    )
    with pytest.raises(ResourceGenerationError, match="内容哈希不匹配"):
        restarted.initialize()


@pytest.mark.asyncio
async def test_build_runtime_keeps_resource_recovery_surface_when_generation_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current 损坏时插件仍可加载，并可用同步命令重建同一 generation。"""

    source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    first = coordinator.synchronize()
    assert first.generation_root is not None
    alias_path = first.generation_root / "alias" / "char_alias.json"
    manifest_path = first.generation_root / "resource_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_hashes"] = {
        "alias/char_alias.json": hashlib.sha256(alias_path.read_bytes()).hexdigest()
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    alias_path.write_text('{"角色甲": ["被篡改"]}', encoding="utf-8")

    restarted = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
    )

    import src.bootstrap as bootstrap_module

    monkeypatch.setattr(
        bootstrap_module,
        "ResourceSnapshotCoordinator",
        lambda *_args, **_kwargs: restarted,
    )
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *_args: None),
        {"login": {"port": 0}},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    snapshots = cast(
        ResourceSnapshotCoordinator, runtime.services["resource_snapshots"]
    )
    assert snapshots.current_snapshot is None
    persisted_status = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
    ).read_status()
    assert persisted_status.current_validation_error == "ResourceGenerationError"
    service = cast(ResourceUpdateService, runtime.services["resource_update_service"])
    status = await service.status()
    assert "当前 generation 不可用" in status.text

    response = await service.sync_resources(None)
    assert "资源已更新完成" in response.text
    assert snapshots.current_snapshot is not None
    assert snapshots.current_snapshot.commit_sha == first.commit_sha
    assert snapshots.current_snapshot.root.is_dir()

    await runtime.terminate()
    assert source.exists()


def test_restart_loads_active_generation_and_removes_orphans_without_touching_panel_custom(
    tmp_path: Path,
) -> None:
    _source, _target, runner = _fixture(tmp_path)
    coordinator = _coordinator(tmp_path, runner)
    result = coordinator.synchronize()
    orphan = coordinator.generations_root / ("f" * 40)
    orphan.mkdir(parents=True)
    (orphan / "stale.txt").write_text("stale", encoding="utf-8")
    panel_custom = tmp_path / "panel_custom"
    panel_custom.mkdir()
    keep = panel_custom / "keep.webp"
    keep.write_bytes(b"panel")

    restarted = ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner,
    )
    snapshot = restarted.initialize()

    assert snapshot is not None
    assert snapshot.commit_sha == result.commit_sha
    assert not orphan.exists()
    assert keep.read_bytes() == b"panel"
    assert (restarted.generations_root / result.commit_sha).is_dir()


def test_bootstrap_removes_alias_write_service_and_panel_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资源运行时不再注入别名写服务或自定义面板服务。"""

    generation_root = tmp_path / "resource_generations" / ("a" * 40)
    generation_root.mkdir(parents=True)
    snapshot = SimpleNamespace(
        root=generation_root,
        player_resources=object(),
        encyclopedia_resources=object(),
    )
    monkeypatch.setattr(
        ResourceSnapshotCoordinator, "initialize", lambda self: snapshot
    )

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    assert "alias_service" not in runtime.services
    assert "panel_service" not in runtime.services
    assert "admin_panel_service" not in runtime.services
    assert "resource_update_service" in runtime.services
