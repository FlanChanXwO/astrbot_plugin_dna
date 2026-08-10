"""v0.1 配置定义与私有资源仓库同步契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.config import DnabySettings, generate_astrbot_schema
from src.infrastructure.resources import (
    GitCommandError,
    GitCommandResult,
    ResourceLocalChangesError,
    ResourceManifest,
    ResourceManifestError,
    ResourceSynchronizer,
)


def test_settings_are_grouped_and_typed() -> None:
    settings = DnabySettings()

    assert settings.login.transport == "local"
    assert settings.login.port == 6189
    assert settings.network.websocket_wait_seconds == 5
    assert settings.sign_in.concurrency == 1
    assert settings.notifications.secret_push_time == "00:30"
    assert settings.display.guide_providers == ["all"]

    loaded = DnabySettings.from_config(
        {
            "login": {"transport": "http_poll", "port": 6200},
            "sign_in": {"sign_time": [1, 30]},
        }
    )
    assert loaded.login.transport == "http_poll"
    assert loaded.login.port == 6200
    assert loaded.sign_in.sign_time == (1, 30)


def test_generated_schema_is_astrbot_compatible(tmp_path: Path) -> None:
    schema = generate_astrbot_schema()
    assert json.loads(Path("_conf_schema.json").read_text(encoding="utf-8")) == schema
    assert set(schema) == {"login", "network", "sign_in", "notifications", "display"}
    assert schema["login"]["type"] == "object"
    assert schema["login"]["items"]["transport"]["options"] == [
        "local",
        "http_poll",
        "sse",
        "ws",
    ]
    assert schema["sign_in"]["items"]["sign_time"]["default"] == [0, 5]

    from astrbot.core import AstrBotConfig

    config = AstrBotConfig(
        config_path=str(tmp_path / "config.json"),
        schema=schema,
    )
    assert config["login"]["port"] == 6189
    assert config["display"]["guide_providers"] == ["all"]


def test_resource_manifest_requires_safe_directories(tmp_path: Path) -> None:
    manifest_path = tmp_path / "resource_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts", "wiki"],
                "resource_version": "2026.08.11",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fonts").mkdir()
    (tmp_path / "wiki").mkdir()

    manifest = ResourceManifest.load(manifest_path)
    assert manifest.resource_version == "2026.08.11"
    assert manifest.validate_root(tmp_path) is manifest

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["../outside"],
                "resource_version": "bad",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ResourceManifestError, match="required_dirs"):
        ResourceManifest.load(invalid_path)


class FakeGit:
    """只返回预设结果，验证同步器不通过 shell 拼接命令。"""

    def __init__(self, responses: dict[tuple[str, ...], GitCommandResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def __call__(
        self, args: tuple[str, ...], cwd: Path | None = None
    ) -> GitCommandResult:
        self.calls.append((args, cwd))
        response = self.responses.get(args)
        if response is None:
            raise AssertionError(f"未预设的 git 调用: {args!r}")
        if response.returncode:
            raise GitCommandError("fake", response.stderr)
        return response


def _write_manifest(repo: Path) -> None:
    (repo / "fonts").mkdir(parents=True)
    (repo / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "test",
            }
        ),
        encoding="utf-8",
    )


def test_resource_sync_clones_once_and_pulls_after_clean_check(tmp_path: Path) -> None:
    target = tmp_path / "resources"
    remote = "git@github.com:FlanChanXwO/dnaby_resources.git"
    clone = FakeGit(
        {
            ("clone", "--depth", "1", remote, str(target)): GitCommandResult(),
            ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
            ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
            ("status", "--porcelain", "--untracked-files=all"): GitCommandResult(),
        }
    )

    def clone_and_create(
        args: tuple[str, ...], cwd: Path | None = None
    ) -> GitCommandResult:
        result = clone(args, cwd)
        if args and args[0] == "clone":
            target.mkdir()
            _write_manifest(target)
        return result

    synchronizer = ResourceSynchronizer(target, remote=remote, runner=clone_and_create)
    result = synchronizer.sync()

    assert result.action == "cloned"
    assert result.resource_version == "test"
    assert [call[0][0] for call in clone.calls] == [
        "clone",
        "rev-parse",
        "remote",
        "status",
    ]

    target2 = tmp_path / "existing"
    target2.mkdir()
    _write_manifest(target2)
    responses = {
        ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
        ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
        ("status", "--porcelain", "--untracked-files=all"): GitCommandResult(),
        ("pull", "--ff-only"): GitCommandResult(),
    }
    existing = FakeGit(responses)
    result = ResourceSynchronizer(target2, remote=remote, runner=existing).sync()
    assert result.action == "updated"
    assert [call[0][0] for call in existing.calls] == [
        "rev-parse",
        "remote",
        "status",
        "pull",
        "rev-parse",
        "remote",
        "status",
    ]


def test_resource_sync_reports_local_changes_without_pull(tmp_path: Path) -> None:
    target = tmp_path / "resources"
    target.mkdir()
    _write_manifest(target)
    remote = "git@github.com:FlanChanXwO/dnaby_resources.git"
    runner = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
            ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
            ("status", "--porcelain", "--untracked-files=all"): GitCommandResult(
                stdout=" M wiki/index.json\n"
            ),
        }
    )

    with pytest.raises(ResourceLocalChangesError, match="本地修改"):
        ResourceSynchronizer(target, remote=remote, runner=runner).sync()
    assert all(call[0][0] != "pull" for call in runner.calls)


def test_git_error_does_not_echo_embedded_credentials() -> None:
    error = GitCommandError(
        "pull",
        "fatal: could not read https://user:token@example.test/private.git?access_token=query-secret\n"
        "Authorization: Bearer bearer-secret",
    )
    assert "user:token@" not in str(error)
    assert "query-secret" not in str(error)
    assert "bearer-secret" not in str(error)
    assert "凭据" in str(error)


def test_generated_metadata_files_are_present() -> None:
    metadata = Path("metadata.yaml").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert "version: v0.1.0" in metadata
    assert Path("logo.png").is_file()
    assert "v0.1.0" in changelog
