"""Goal 6 T10：资源轻量加载与完整校验的 Red 契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.infrastructure.resources import (
    RUNTIME_RESOURCE_DIRECTORIES,
    ResourceGenerationError,
    ResourceGenerationValidator,
    ResourceSnapshotCoordinator,
)
from src.infrastructure.resources import generation as generation_module
from src.modules.operations import messages
from src.modules.operations.resource_service import ResourceUpdateService

GENERATION = "a" * 40


class _ForbiddenRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        args: tuple[str, ...],
        cwd: Path | None = None,
    ) -> Any:
        del cwd
        self.calls.append(args)
        raise AssertionError("轻量资源读取不得调用 Git")


class _ForbiddenValidator:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, root: Path, commit_sha: str) -> Any:
        del root, commit_sha
        self.calls += 1
        raise AssertionError("轻量资源读取不得运行完整 validator")


def _coordinator(
    tmp_path: Path,
    *,
    runner: Any | None = None,
    validator: Any | None = None,
) -> ResourceSnapshotCoordinator:
    return ResourceSnapshotCoordinator(
        tmp_path / "resources",
        generations_root=tmp_path / "resource_generations",
        runner=runner or _ForbiddenRunner(),
        validator=validator or ResourceGenerationValidator(),
    )


def _write_pointer(
    generations_root: Path,
    generation: str = GENERATION,
    *,
    content_sha256: str | None = None,
) -> Path:
    root = generations_root / generation
    root.mkdir(parents=True, exist_ok=True)
    pointer: dict[str, str] = {"generation": generation}
    if content_sha256 is not None:
        pointer["content_sha256"] = content_sha256
    generations_root.mkdir(parents=True, exist_ok=True)
    (generations_root / "current.json").write_text(
        json.dumps(pointer) + "\n",
        encoding="utf-8",
    )
    return root


def _write_light_generation(generations_root: Path) -> Path:
    root = _write_pointer(generations_root)
    (root / "fonts").mkdir()
    (root / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts"],
                "resource_version": "light-v1",
            }
        ),
        encoding="utf-8",
    )
    image = root / "images" / "role_avatar" / "broken.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not-a-png")
    return root


def _write_complete_generation(
    generations_root: Path,
    *,
    version: str = "complete-v1",
) -> Path:
    root = _write_pointer(generations_root, generation="b" * 40)
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
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(
        image_path,
        format="PNG",
    )
    Image.new("RGBA", (2, 2), (0, 255, 0, 255)).save(
        root / "wiki" / "role" / "角色甲.png",
        format="PNG",
    )
    (root / "fonts" / "dna_fonts.ttf").write_bytes(b"\x00\x01\x00\x00fixture")
    return root


def test_load_current_without_resources_returns_none_without_git_or_validation(
    tmp_path: Path,
) -> None:
    """没有 current generation 时，插件仍可加载且不触发远程或完整校验。"""

    runner = _ForbiddenRunner()
    validator = _ForbiddenValidator()
    coordinator = _coordinator(tmp_path, runner=runner, validator=validator)

    assert coordinator.load_current() is None
    assert runner.calls == []
    assert validator.calls == 0


def test_load_current_reads_metadata_without_tree_scan_or_image_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轻量读取只装载 current metadata，不遍历资源树或解码图片。"""

    generations_root = tmp_path / "resource_generations"
    root = _write_light_generation(generations_root)
    runner = _ForbiddenRunner()
    validator = _ForbiddenValidator()
    coordinator = _coordinator(tmp_path, runner=runner, validator=validator)

    def forbidden_rglob(self: Path, pattern: str):
        del self, pattern
        raise AssertionError("轻量资源读取不得遍历资源树")

    def forbidden_open(*args: Any, **kwargs: Any):
        del args, kwargs
        raise AssertionError("轻量资源读取不得解码图片")

    monkeypatch.setattr(generation_module.Path, "rglob", forbidden_rglob)
    monkeypatch.setattr(generation_module.Image, "open", forbidden_open)

    snapshot = coordinator.load_current()

    assert snapshot is not None
    assert snapshot.commit_sha == GENERATION
    assert snapshot.root == root.resolve()
    assert snapshot.resource_version == "light-v1"
    assert snapshot.content_sha256 == ""
    assert runner.calls == []
    assert validator.calls == 0


def test_load_current_rejects_a_corrupt_current_pointer_explicitly(
    tmp_path: Path,
) -> None:
    """current 指针损坏时显式失败，不能伪造成无资源。"""

    generations_root = tmp_path / "resource_generations"
    generations_root.mkdir()
    (generations_root / "current.json").write_text(
        json.dumps({"generation": "../escape"}),
        encoding="utf-8",
    )

    with pytest.raises(ResourceGenerationError, match="generation 指针无效"):
        _coordinator(tmp_path).load_current()


@pytest.mark.parametrize("damage", ["manifest", "alias", "redeem", "schema", "image"])
def test_validate_current_runs_complete_generation_checks(
    tmp_path: Path,
    damage: str,
) -> None:
    """完整校验必须覆盖 manifest、JSON/schema、alias 与图片解码。"""

    generations_root = tmp_path / "resource_generations"
    root = _write_complete_generation(generations_root)
    if damage == "manifest":
        (root / "resource_manifest.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "required_dirs": ["fonts"],
                    "resource_version": "broken",
                }
            ),
            encoding="utf-8",
        )
    elif damage == "alias":
        (root / "alias" / "char_alias.json").write_text(
            json.dumps({"角色甲": []}),
            encoding="utf-8",
        )
    elif damage == "redeem":
        (root / "data" / "redeem_codes.json").write_text(
            json.dumps({"format_version": 1, "data": [{"code": ""}]}),
            encoding="utf-8",
        )
    elif damage == "schema":
        (root / "schemas" / "redeem-codes.v1.schema.json").write_text(
            json.dumps({"$schema": "", "type": "object", "required": []}),
            encoding="utf-8",
        )
    else:
        (root / "images" / "role_avatar" / "1.png").write_bytes(b"not-a-png")

    coordinator = _coordinator(tmp_path)
    assert coordinator.load_current() is not None

    with pytest.raises(ResourceGenerationError, match="资源候选 generation 校验失败"):
        coordinator.validate_current()


@pytest.mark.asyncio
async def test_missing_generation_only_affects_resource_reads_and_status_stays_available(
    tmp_path: Path,
) -> None:
    """资源缺失只影响资源读取，状态查询仍应返回明确的空状态。"""

    coordinator = _coordinator(tmp_path)
    assert coordinator.load_current() is None
    with coordinator.optional_lease() as snapshot:
        assert snapshot is None

    def forbidden_sync() -> Any:
        raise AssertionError("资源状态不得触发同步")

    service = ResourceUpdateService(
        synchronize=forbidden_sync,
        resource_root=tmp_path / "resources",
        resource_snapshots=coordinator,
    )
    response = await service.status()

    assert messages.RESOURCE_STATUS_EMPTY in response.text


@pytest.mark.asyncio
async def test_resource_status_does_not_trigger_full_validation_or_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资源状态只读 manifest 和目录存在性，不启动同步、PIL 或完整 hash。"""

    resource_root = tmp_path / "resources"
    (resource_root / "fonts").mkdir(parents=True)
    (resource_root / "resource_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "required_dirs": ["fonts", "images"],
                "resource_version": "status-v1",
            }
        ),
        encoding="utf-8",
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("资源状态不得触发完整重操作")

    monkeypatch.setattr(ResourceGenerationValidator, "validate", forbidden)
    monkeypatch.setattr(generation_module, "_content_sha256", forbidden)
    monkeypatch.setattr(generation_module.Image, "open", forbidden)

    def forbidden_sync() -> Any:
        raise AssertionError("资源状态不得触发同步")

    service = ResourceUpdateService(
        synchronize=forbidden_sync,
        resource_root=resource_root,
    )
    response = await service.status()

    assert "manifest: v1" in response.text
    assert "必需目录: 1/2 存在" in response.text
