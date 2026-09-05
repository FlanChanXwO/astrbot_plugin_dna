"""Goal 3 Task 19：三仓资源契约与旧数据目录兼容回归。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path

from PIL import Image

from src.infrastructure.http.encyclopedia import DnaApiEncyclopediaTransport
from src.infrastructure.resources import (
    DEFAULT_RESOURCE_REMOTE,
    ResourceSnapshotCoordinator,
    run_git,
)

REQUIRED_DIRS = (
    "fonts",
    "images",
    "panel",
    "alias",
    "data",
    "schemas",
    "wiki/role",
    "wiki/weapon",
    "wiki/spirit",
    "guide",
    "weekly_item",
    "calendar",
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


def _git_bytes(*args: str, cwd: Path | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def _resource_repo_root() -> Path:
    configured = os.environ.get("DNA_RESOURCE_REPO")
    if configured:
        candidate = Path(configured).expanduser()
        if (candidate / "resource_manifest.json").is_file():
            return candidate
        raise AssertionError(
            f"DNA_RESOURCE_REPO 不是有效的 astrbot_plugin_dna_resources checkout: {candidate}"
        )

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "astrbot_plugin_dna_resources"
        if (candidate / "resource_manifest.json").is_file():
            return candidate
    raise AssertionError("找不到 astrbot_plugin_dna_resources checkout")


def _resource_files(root: Path, redeem_codes: object, public_resources: Path) -> None:
    for relative in REQUIRED_DIRS:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").write_text("\n", encoding="utf-8")
    public_manifest = json.loads(
        (public_resources / "resource_manifest.json").read_text(encoding="utf-8"),
    )
    assert tuple(public_manifest["required_dirs"]) == REQUIRED_DIRS
    (root / "resource_manifest.json").write_text(
        json.dumps(public_manifest),
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
        json.dumps({"format_version": 1, "data": redeem_codes}),
        encoding="utf-8",
    )
    (root / "schemas" / "redeem-codes.v1.schema.json").write_text(
        (public_resources / "schemas" / "redeem-codes.v1.schema.json").read_text(
            encoding="utf-8",
        ),
        encoding="utf-8",
    )
    # 使用真实可解码图片，匹配插件对候选素材的完整 PIL 校验。
    image_path = root / "images" / "role_avatar" / "1101.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(image_path, format="PNG")
    (root / "fonts" / "dna_fonts.ttf").write_bytes(b"\x00\x01\x00\x00task19")
    (root / "README.md").write_text("Task 19 fixture\n", encoding="utf-8")


def _commit(source: Path, message: str) -> str:
    _git("add", ".", cwd=source)
    _git("commit", "-m", message, cwd=source)
    return _git("rev-parse", "HEAD", cwd=source).strip()


def _tree_fixture(source: Path, commit_sha: str) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    contents: dict[str, str] = {}
    for line in _git("ls-tree", "-r", "--long", commit_sha, cwd=source).splitlines():
        mode, entry_type, sha, size_and_path = line.split(" ", 3)
        size, path = size_and_path.split("\t", 1)
        entries.append(
            {
                "path": path,
                "type": entry_type,
                "mode": mode,
                "sha": sha,
                "size": int(size),
            },
        )
        contents[path] = base64.b64encode(
            _git_bytes("cat-file", "blob", sha, cwd=source),
        ).decode("ascii")
    return {"headSha": commit_sha, "entries": entries, "contents": contents}


class LocalBareRunner:
    """把 canonical GitHub origin 映射到本地 bare fixture。"""

    def __init__(self, bare: Path) -> None:
        self.bare = bare
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        args: tuple[str, ...],
        cwd: Path | None = None,
    ):
        self.calls.append(args)
        operation = args[2] if args[:1] == ("-c",) else args[0]
        if operation in {"clone", "fetch", "pull"}:
            mapping = f"url.{self.bare.as_uri()}.insteadOf={DEFAULT_RESOURCE_REMOTE}"
            result = run_git(("-c", mapping, *args), cwd)
        else:
            result = run_git(args, cwd)
        if operation == "clone":
            target = Path(args[-1])
            _git("remote", "set-url", "origin", DEFAULT_RESOURCE_REMOTE, cwd=target)
        return result


def _editor_root() -> Path:
    configured = os.environ.get("DNA_RESOURCE_EDITOR")
    if configured:
        candidate = Path(configured).expanduser()
        if (candidate / "package.json").is_file():
            return candidate
        raise AssertionError(
            f"DNA_RESOURCE_EDITOR 不是有效的 dna-resource-editor checkout: {candidate}"
        )

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "dna-resource-editor"
        if (candidate / "package.json").is_file():
            return candidate
    raise AssertionError("找不到 dna-resource-editor checkout")


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object], LocalBareRunner]:
    bare = tmp_path / "remote.git"
    source = tmp_path / "source"
    source.mkdir()
    _git("init", "--bare", str(bare), cwd=tmp_path)
    _git("init", "--initial-branch=main", cwd=source)
    _git("config", "user.name", "Task 19 Fixture", cwd=source)
    _git("config", "user.email", "task19@example.invalid", cwd=source)
    _git("remote", "add", "fixture", bare.as_uri(), cwd=source)

    public_resources = _resource_repo_root()
    valid_codes = [
        {
            "code": "TASK19-CODE",
            "reward": "测试奖励",
            "valid_from": "2020-01-01T00:00:00+08:00",
            "expires_at": "2099-01-01T00:00:00+08:00",
            "platforms": ["pc"],
            "servers": ["cn"],
        },
    ]
    _resource_files(source, valid_codes, public_resources)
    legal_sha = _commit(source, "legal resource submission")
    _git("push", "fixture", "HEAD:main", cwd=source)

    _git("checkout", "-b", "candidate-invalid", cwd=source)
    (source / "schemas" / "redeem-codes.v1.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["format_version", "data", "unexpected"],
            }
        ),
        encoding="utf-8",
    )
    invalid_sha = _commit(source, "invalid redeem contract")
    _git("push", "fixture", "HEAD:candidate-invalid", cwd=source)

    _git("checkout", "main", cwd=source)
    _git("checkout", "-b", "candidate-editor-code", cwd=source)
    (source / "worker").mkdir()
    (source / "worker" / "index.ts").write_text("export const not_a_resource = true;\n", encoding="utf-8")
    editor_sha = _commit(source, "editor code must stay out of resources")
    _git("push", "fixture", "HEAD:candidate-editor-code", cwd=source)
    _git("checkout", "main", cwd=source)

    fixture = {
        "legal": _tree_fixture(source, legal_sha),
        "invalidRedeem": _tree_fixture(source, invalid_sha),
        "editorCode": _tree_fixture(source, editor_sha),
    }
    return source, bare, fixture, LocalBareRunner(bare)


def test_worker_check_and_plugin_generation_consume_one_contract_snapshot(
    tmp_path: Path,
) -> None:
    source, bare, fixture, runner = _fixture(tmp_path)
    fixture_path = tmp_path / "task19-fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    environment = os.environ.copy()
    environment["DNA_TASK19_FIXTURE"] = str(fixture_path)
    result = subprocess.run(
        [
            "npm",
            "run",
            "test:task19",
            "--",
            "--run",
            "test/task19-contract.test.ts",
        ],
        cwd=_editor_root(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    data_dir = tmp_path / "plugin-data"
    cache_root = data_dir / "resources"
    generations_root = data_dir / "resource_generations"
    panel_custom = data_dir / "panel_custom"
    panel_custom.mkdir(parents=True)
    (panel_custom / "keep.webp").write_bytes(b"custom-panel")
    (data_dir / "dnaby.sqlite3").write_bytes(b"legacy-database")
    (data_dir / "subscriptions.json").write_text('{"legacy": true}\n', encoding="utf-8")

    runner(
        (
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            "main",
            "--no-tags",
            DEFAULT_RESOURCE_REMOTE,
            str(cache_root),
        ),
        cache_root.parent,
    )

    coordinator = ResourceSnapshotCoordinator(
        cache_root,
        generations_root=generations_root,
        runner=runner,
    )
    assert coordinator.initialize() is None
    assert (cache_root / "resource_manifest.json").is_file()
    result = coordinator.synchronize()
    snapshot = coordinator.current_snapshot

    assert snapshot is not None
    assert result.commit_sha == fixture["legal"]["headSha"]
    assert result.resource_version == json.loads(
        (snapshot.root / "resource_manifest.json").read_text(encoding="utf-8"),
    )["resource_version"]
    assert snapshot.root == generations_root / result.commit_sha
    assert not (snapshot.root / "worker").exists()
    assert not (cache_root / "worker").exists()
    assert not any(
        path.name.startswith((".candidate-", ".archive-"))
        for path in generations_root.iterdir()
    )
    assert _git("remote", "get-url", "origin", cwd=cache_root).strip() == DEFAULT_RESOURCE_REMOTE
    assert _git("branch", "--show-current", cwd=cache_root).strip() == "main"
    assert _git(
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/remotes/origin",
        cwd=cache_root,
    ).splitlines() == ["origin/main"]
    assert (panel_custom / "keep.webp").read_bytes() == b"custom-panel"
    assert (data_dir / "dnaby.sqlite3").read_bytes() == b"legacy-database"
    assert (data_dir / "subscriptions.json").read_text(encoding="utf-8") == '{"legacy": true}\n'

    restarted = ResourceSnapshotCoordinator(
        cache_root,
        generations_root=generations_root,
        runner=runner,
    )
    restored = restarted.initialize()
    assert restored is not None
    assert restored.commit_sha == result.commit_sha
    assert (panel_custom / "keep.webp").read_bytes() == b"custom-panel"

    raw_payload = json.loads((snapshot.root / "data" / "redeem_codes.json").read_text(encoding="utf-8"))
    transport = DnaApiEncyclopediaTransport(
        object(),
        code_provider=lambda _actor: raw_payload,
    )
    code_snapshot = asyncio.run(transport.get_codes(object()))
    assert code_snapshot.codes == ("TASK19-CODE",)

    assert source.exists()
    assert bare.exists()
