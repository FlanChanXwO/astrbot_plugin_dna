"""Goal 3 Task 16：资源加速配置与单分支 Git 同步契约。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from src.bootstrap import build_runtime
from src.infrastructure.config import (
    DnabySettings,
    ResourceSettings,
    generate_astrbot_schema,
)
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.resources import (
    BUILTIN_GITHUB_ACCELERATION_PREFIXES,
    DEFAULT_RESOURCE_REMOTE,
    GitCommandError,
    GitCommandResult,
    ResourceSnapshotCoordinator,
    ResourceSynchronizer,
    ResourceSyncResult,
    accelerate_github_url,
    build_git_instead_of_config,
    normalize_github_repository_url,
    run_git,
)
from src.infrastructure.resources.manifest import RUNTIME_RESOURCE_DIRECTORIES
from src.modules.operations.resource_service import ResourceUpdateService


def _write_manifest(repository: Path, *, version: str = "fixture") -> None:
    for relative in RUNTIME_RESOURCE_DIRECTORIES:
        directory = repository / relative
        directory.mkdir(parents=True, exist_ok=True)
        # Git 不跟踪空目录；占位文件让真实 bare remote fixture 保留完整布局。
        (directory / ".keep").write_text("fixture\n", encoding="utf-8")
    (repository / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": list(RUNTIME_RESOURCE_DIRECTORIES),
                "resource_version": version,
            }
        ),
        encoding="utf-8",
    )


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


def _git_command(args: tuple[str, ...]) -> str:
    if args[:1] == ("-c",):
        return args[2]
    return args[0]


def test_resource_settings_expose_acceleration_modes_and_normalize_custom_url() -> None:
    settings = DnabySettings()
    assert settings.resources.github_acceleration == "off"
    assert settings.resources.acceleration_prefix is None

    for mode, expected in BUILTIN_GITHUB_ACCELERATION_PREFIXES.items():
        configured = ResourceSettings(github_acceleration=mode)
        assert configured.acceleration_prefix == expected

    custom = ResourceSettings(
        github_acceleration="custom",
        custom_github_acceleration_url=" https://mirror.example/gh/// ",
    )
    assert custom.custom_github_acceleration_url == "https://mirror.example/gh"
    assert custom.acceleration_prefix == "https://mirror.example/gh"


def test_bootstrap_passes_resource_acceleration_to_downloader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, str | None]] = []

    def fake_synchronize(self: ResourceSnapshotCoordinator) -> ResourceSyncResult:
        calls.append((self.repository.parent, self.acceleration_prefix))
        return ResourceSyncResult(self.repository, "updated", "fixture")

    monkeypatch.setattr(
        "src.infrastructure.resources.ResourceSnapshotCoordinator.synchronize",
        fake_synchronize,
    )
    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {
            "resources": {
                "github_acceleration": "custom",
                "custom_github_acceleration_url": "https://mirror.example/gh/",
            }
        },
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    cast(ResourceUpdateService, runtime.services["resource_update_service"]).synchronize()

    assert calls == [(tmp_path, "https://mirror.example/gh")]


@pytest.mark.parametrize(
    "value",
    [
        "ftp://mirror.example",
        "https://user:secret@mirror.example",
        "https://mirror.example/path?token=secret",
        "https://mirror.example/path#fragment",
        "https://mirror.example/path\nnext",
        "https://mirror.example/path\x00",
    ],
)
def test_custom_acceleration_url_rejects_unsafe_values_without_echoing_input(
    value: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        ResourceSettings(
            github_acceleration="custom",
            custom_github_acceleration_url=value,
        )

    assert "secret" not in str(error.value)
    assert "token=secret" not in str(error.value)


def test_resource_schema_projects_acceleration_group() -> None:
    schema = generate_astrbot_schema()
    assert set(schema) == {
        "login",
        "network",
        "sign_in",
        "notifications",
        "display",
        "resources",
    }
    resources = schema["resources"]
    assert resources["type"] == "object"
    assert resources["items"]["github_acceleration"]["options"] == [
        "off",
        "edgeone",
        "hk",
        "gh_proxy",
        "dpik",
        "custom",
    ]
    assert resources["items"]["github_acceleration"]["default"] == "off"
    assert resources["items"]["custom_github_acceleration_url"]["default"] == ""


@pytest.mark.parametrize(
    "remote",
    [
        "http://github.com/owner/repo.git",
        "https://user:secret@github.com/owner/repo.git",
        "https://github.com/owner/repo.git?token=secret",
        "https://evil.example/owner/repo.git",
        "https://github.com/owner/../repo.git",
    ],
)
def test_resource_remote_must_be_canonical_github_https_without_echoing_credentials(
    remote: str,
) -> None:
    with pytest.raises(ValueError) as error:
        normalize_github_repository_url(remote)

    assert "secret" not in str(error.value)
    assert "token" not in str(error.value)

    with pytest.raises(ValueError):
        ResourceSynchronizer(Path("/tmp/resource-fixture"), remote=remote)


def test_github_urls_and_git_config_keep_canonical_origin() -> None:
    assert normalize_github_repository_url("https://github.com/Owner/Repo") == (
        "https://github.com/Owner/Repo.git"
    )
    prefix = "https://edgeone.gh-proxy.com"
    assert build_git_instead_of_config(prefix) == (
        "url.https://edgeone.gh-proxy.com/https://github.com/.insteadOf=https://github.com/"
    )
    assert accelerate_github_url(
        "https://raw.githubusercontent.com/Owner/Repo/main/data/redeem_codes.json",
        prefix,
    ) == (
        "https://edgeone.gh-proxy.com/"
        "https://raw.githubusercontent.com/Owner/Repo/main/data/redeem_codes.json"
    )


def test_clone_uses_depth_single_main_no_tags_and_temporary_mirror_config(
    tmp_path: Path,
) -> None:
    target = tmp_path / "resources"
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
        del cwd
        calls.append(args)
        command = _git_command(args)
        if command == "clone":
            target.mkdir()
            _write_manifest(target)
            return GitCommandResult()
        if command == "rev-parse":
            return GitCommandResult(stdout="true\n")
        if command == "remote":
            return GitCommandResult(stdout=f"{DEFAULT_RESOURCE_REMOTE}\n")
        if command == "symbolic-ref":
            return GitCommandResult(stdout="main\n")
        if command == "status":
            return GitCommandResult()
        raise AssertionError(f"unexpected git command: {args!r}")

    result = ResourceSynchronizer(
        target,
        acceleration_prefix="https://edgeone.gh-proxy.com",
        runner=runner,
    ).sync()

    assert result.action == "cloned"
    assert calls[0] == (
        "-c",
        build_git_instead_of_config("https://edgeone.gh-proxy.com"),
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        "main",
        "--no-tags",
        DEFAULT_RESOURCE_REMOTE,
        str(target),
    )
    network_calls = [call for call in calls if _git_command(call) in {"clone", "fetch", "pull"}]
    local_calls = [call for call in calls if _git_command(call) not in {"clone", "fetch", "pull"}]
    assert network_calls and all(call[:1] == ("-c",) for call in network_calls)
    assert local_calls and all(call[:1] != ("-c",) for call in local_calls)


def test_mirror_failure_is_visible_without_direct_fallback(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
        del cwd
        calls.append(args)
        raise GitCommandError("clone", "mirror unavailable")

    with pytest.raises(GitCommandError, match="mirror unavailable"):
        ResourceSynchronizer(
            tmp_path / "resources",
            acceleration_prefix="https://mirror.example/gh",
            runner=runner,
        ).sync()

    assert len(calls) == 1
    assert calls[0][:1] == ("-c",)
    assert build_git_instead_of_config("https://mirror.example/gh") in calls[0]


def test_existing_checkout_pulls_only_main_without_tags(tmp_path: Path) -> None:
    target = tmp_path / "resources"
    target.mkdir()
    _write_manifest(target)
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
        del cwd
        calls.append(args)
        command = _git_command(args)
        if command == "rev-parse":
            return GitCommandResult(stdout="true\n")
        if command == "remote":
            return GitCommandResult(stdout=f"{DEFAULT_RESOURCE_REMOTE}\n")
        if command == "symbolic-ref":
            return GitCommandResult(stdout="main\n")
        if command == "status":
            return GitCommandResult()
        if command == "pull":
            assert args[2:] == ("pull", "--ff-only", "--no-tags", "origin", "main")
            return GitCommandResult()
        raise AssertionError(f"unexpected git command: {args!r}")

    result = ResourceSynchronizer(
        target,
        acceleration_prefix="https://hk.gh-proxy.com",
        runner=runner,
    ).sync()

    assert result.action == "updated"
    pull_calls = [call for call in calls if _git_command(call) == "pull"]
    assert len(pull_calls) == 1
    assert "--tags" not in pull_calls[0]
    assert pull_calls[0][-2:] == ("origin", "main")


def test_local_bare_fixture_clones_only_main_and_preserves_canonical_origin(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "remote.git"
    source = tmp_path / "source"
    source.mkdir()
    _git("init", "--bare", str(bare))
    _git("init", "--initial-branch=main", cwd=source)
    _git("config", "user.name", "Goal 3 Fixture", cwd=source)
    _git("config", "user.email", "goal3@example.invalid", cwd=source)
    _write_manifest(source)
    (source / "main.txt").write_text("main\n", encoding="utf-8")
    _git("add", ".", cwd=source)
    _git("commit", "-m", "main resource", cwd=source)
    _git("checkout", "-b", "feature", cwd=source)
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git("add", "feature.txt", cwd=source)
    _git("commit", "-m", "feature resource", cwd=source)
    _git("tag", "feature-tag", cwd=source)
    _git("checkout", "main", cwd=source)
    _git("remote", "add", "fixture", bare.as_uri(), cwd=source)
    _git("push", "fixture", "main", "feature", "--tags", cwd=source)

    class LocalBareRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(
            self, args: tuple[str, ...], cwd: Path | None = None
        ) -> GitCommandResult:
            self.calls.append(args)
            if _git_command(args) in {"clone", "pull"}:
                mapping = f"url.{bare.as_uri()}.insteadOf={DEFAULT_RESOURCE_REMOTE}"
                result = run_git(("-c", mapping, *args), cwd)
            else:
                result = run_git(args, cwd)
            if _git_command(args) == "clone":
                # Git 可能把 insteadOf 重写后的 file URL 保存为 origin；测试 fixture
                # 显式恢复产品契约要求的规范 GitHub origin。
                _git("remote", "set-url", "origin", DEFAULT_RESOURCE_REMOTE, cwd=target)
            return result

    runner = LocalBareRunner()
    target = tmp_path / "resources"
    result = ResourceSynchronizer(target, runner=runner).sync()

    assert result.repository == target
    assert (
        _git("remote", "get-url", "origin", cwd=target).strip()
        == DEFAULT_RESOURCE_REMOTE
    )
    assert _git("branch", "--show-current", cwd=target).strip() == "main"
    refs = _git(
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/remotes/origin",
        cwd=target,
    ).splitlines()
    assert refs == ["origin/main"]
    assert not (target / "feature.txt").exists()
    assert _git("tag", cwd=target).strip() == ""
    assert any(_git_command(call) == "clone" for call in runner.calls)
