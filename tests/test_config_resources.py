"""v0.1 配置定义与公共资源仓库同步契约。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PIL import Image

from src.bootstrap import build_runtime
from src.infrastructure.config import DnabySettings, generate_astrbot_schema
from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.rendering.player import ResourceMap
from src.infrastructure.resources import (
    GitCommandError,
    GitCommandResult,
    ResourceLocalChangesError,
    ResourceManifest,
    ResourceManifestError,
    ResourceSnapshotCoordinator,
    ResourceSynchronizer,
)
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.manifest import RUNTIME_RESOURCE_DIRECTORIES
from src.modules.admin.aliases import AdminAliasService
from src.modules.player.service import PlayerService


def test_settings_are_grouped_and_typed() -> None:
    settings = DnabySettings()

    assert settings.login.transport == "local"
    assert settings.login.port == 6189
    assert settings.network.websocket_wait_seconds == 5
    assert settings.sign_in.concurrency == 1
    assert not hasattr(settings.notifications, "secret_push_time")
    assert settings.display.guide_providers == ["all"]

    loaded = DnabySettings.from_config(
        {
            "login": {"transport": "http_poll", "port": 6200},
            "sign_in": {"sign_time": "01:30"},
        }
    )
    assert loaded.login.transport == "http_poll"
    assert loaded.login.port == 6200
    assert loaded.sign_in.sign_time == "01:30"


def test_generated_schema_is_astrbot_compatible(tmp_path: Path) -> None:
    schema = generate_astrbot_schema()
    assert json.loads(Path("_conf_schema.json").read_text(encoding="utf-8")) == schema
    assert set(schema) == {
        "login",
        "network",
        "sign_in",
        "notifications",
        "display",
        "resources",
        "cache",
        "agent_tools",
    }
    assert schema["login"]["type"] == "object"
    assert schema["login"]["items"]["transport"]["options"] == [
        "local",
        "http_poll",
        "sse",
        "ws",
    ]
    assert schema["sign_in"]["items"]["sign_time"]["default"] == "00:05"

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


def test_runtime_resource_layout_includes_shared_renderer_textures() -> None:
    """公共卡片纹理必须和字体/图片一样属于 manifest 运行期目录契约。"""

    assert "textures" in RUNTIME_RESOURCE_DIRECTORIES


def test_resource_manifest_requires_complete_runtime_layout(tmp_path: Path) -> None:
    """资源仓库必须声明 renderer 与百科索引共同消费的完整目录布局。"""

    for relative in (
        "fonts",
        "images",
        "panel",
        "alias",
        "wiki/role",
        "wiki/weapon",
        "wiki/spirit",
        "guide",
        "weekly_item",
        "calendar",
        "textures",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    incomplete = ResourceManifest(
        format_version=1,
        required_dirs=("fonts", "images", "panel", "wiki", "guide"),
        resource_version="test",
    )

    with pytest.raises(ResourceManifestError, match="运行期目录"):
        incomplete.validate_runtime_layout(tmp_path)


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
    for relative in RUNTIME_RESOURCE_DIRECTORIES:
        (repo / relative).mkdir(parents=True, exist_ok=True)
    (repo / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": list(RUNTIME_RESOURCE_DIRECTORIES),
                "resource_version": "test",
            }
        ),
        encoding="utf-8",
    )


def test_resource_sync_rejects_manifest_missing_runtime_layout(tmp_path: Path) -> None:
    """Git 状态正常也不能绕过 renderer/百科所需的资源目录契约。"""

    target = tmp_path / "resources"
    target.mkdir()
    (target / "fonts").mkdir()
    (target / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "incomplete",
            },
        ),
        encoding="utf-8",
    )
    remote = "https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git"
    runner = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
            ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
            ("symbolic-ref", "--short", "HEAD"): GitCommandResult(stdout="main\n"),
            ("status", "--porcelain", "--untracked-files=all"): GitCommandResult(),
        },
    )

    with pytest.raises(ResourceManifestError, match="运行期目录"):
        ResourceSynchronizer(target, remote=remote, runner=runner).validate()


@pytest.mark.asyncio
async def test_bootstrap_injects_complete_runtime_resource_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整 verified snapshot 下，两个查询模块必须读取同一个资源根。"""

    data_dir = tmp_path / "plugin-data"
    resource_root = data_dir / "resources"
    _write_manifest(resource_root)
    font = resource_root / "fonts" / "dna_fonts.ttf"
    font.write_bytes(b"fixture-font")
    avatar = resource_root / "images" / "role_avatar" / "101.png"
    panel = resource_root / "panel" / "101.png"
    role_wiki = resource_root / "wiki" / "role" / "角色甲.png"
    weapon_wiki = resource_root / "wiki" / "weapon" / "武器甲.png"
    spirit_wiki = resource_root / "wiki" / "spirit" / "魔灵甲.png"
    guide = resource_root / "guide" / "攻略组" / "角色甲-build.png"
    weekly = resource_root / "weekly_item" / "item_100.png"
    calendar = resource_root / "calendar" / "calendar-a.png"
    for path, color in (
        (avatar, "red"),
        (panel, "purple"),
        (role_wiki, "blue"),
        (weapon_wiki, "teal"),
        (spirit_wiki, "navy"),
        (guide, "green"),
        (weekly, "yellow"),
        (calendar, "orange"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (9, 11), color).save(path)
    (resource_root / "alias" / "char_alias.json").write_text(
        json.dumps({"角色甲": ["小甲"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (resource_root / "alias" / "weapon_alias.json").write_text(
        json.dumps({"武器甲": ["大剑"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(
        commit_sha="a" * 40,
        root=resource_root,
        player_resources=ResourceMap.from_root(resource_root),
        encyclopedia_resources=EncyclopediaResourceStore.from_root(
            resource_root,
            custom_alias_path=data_dir / "alias_custom.json",
            custom_weapon_alias_path=data_dir / "weapon_alias_custom.json",
        ),
    )
    def initialize_verified(self: ResourceSnapshotCoordinator):
        self._current = snapshot
        return snapshot

    monkeypatch.setattr(
        ResourceSnapshotCoordinator,
        "initialize",
        initialize_verified,
    )

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(data_dir / "dnaby.sqlite3"),
    )
    player_service = cast(PlayerService, runtime.services["player_service"])
    encyclopedia_resources = cast(
        EncyclopediaResourceStore,
        runtime.services["encyclopedia_resources"],
    )

    assert player_service.renderer.resources.font_path == font
    player_resources = cast(ResourceMap, player_service.renderer.resources)
    assert player_resources.original_panel(101) == panel
    assert player_resources.load("role_avatar", "101", None) is not None
    assert encyclopedia_resources.font_path == font
    assert encyclopedia_resources.wiki_asset("小甲") == ("role", role_wiki)
    assert encyclopedia_resources.wiki_asset("大剑") == ("weapon", weapon_wiki)
    assert encyclopedia_resources.wiki_asset("魔灵甲") == ("spirit", spirit_wiki)
    assert encyclopedia_resources.guides_for("小甲", ("攻略组",))[0].path == guide
    assert encyclopedia_resources.weekly_asset(100) == weekly
    assert encyclopedia_resources.calendar_asset("calendar-a.png") == calendar

    alias_service = cast(AdminAliasService, runtime.services["admin_alias_service"])
    assert (await alias_service.add_alias("角色甲", "运行期小甲")).ok is True
    assert (await alias_service.add_weapon_alias("武器甲", "运行期大剑")).ok is True
    updated_resources = cast(
        EncyclopediaResourceStore,
        runtime.services["encyclopedia_resources"],
    )
    assert updated_resources.aliases.resolve_char("运行期小甲") == "角色甲"
    assert updated_resources.aliases.resolve_weapon("运行期大剑") == "武器甲"


def test_resource_sync_clones_once_and_pulls_after_clean_check(tmp_path: Path) -> None:
    target = tmp_path / "resources"
    remote = "https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git"
    clone = FakeGit(
        {
            (
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                "main",
                "--no-tags",
                remote,
                str(target),
            ): GitCommandResult(),
            ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
            ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
            ("symbolic-ref", "--short", "HEAD"): GitCommandResult(stdout="main\n"),
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
        "symbolic-ref",
        "status",
    ]

    target2 = tmp_path / "existing"
    target2.mkdir()
    _write_manifest(target2)
    responses = {
        ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
        ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
        ("symbolic-ref", "--short", "HEAD"): GitCommandResult(stdout="main\n"),
        ("status", "--porcelain", "--untracked-files=all"): GitCommandResult(),
        ("pull", "--ff-only", "--no-tags", "origin", "main"): GitCommandResult(),
    }
    existing = FakeGit(responses)
    result = ResourceSynchronizer(target2, remote=remote, runner=existing).sync()
    assert result.action == "updated"
    assert [call[0][0] for call in existing.calls] == [
        "rev-parse",
        "remote",
        "symbolic-ref",
        "status",
        "pull",
        "rev-parse",
        "remote",
        "symbolic-ref",
        "status",
    ]


def test_resource_sync_reports_local_changes_without_pull(tmp_path: Path) -> None:
    target = tmp_path / "resources"
    target.mkdir()
    _write_manifest(target)
    remote = "https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git"
    runner = FakeGit(
        {
            ("rev-parse", "--is-inside-work-tree"): GitCommandResult(stdout="true\n"),
            ("remote", "get-url", "origin"): GitCommandResult(stdout=f"{remote}\n"),
            ("symbolic-ref", "--short", "HEAD"): GitCommandResult(stdout="main\n"),
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
    assert "version: v0.2.0" in metadata
    assert 'astrbot_version: ">=4.26.0"' in metadata
    assert Path("logo.png").is_file()
    assert "v0.2.0" in changelog
