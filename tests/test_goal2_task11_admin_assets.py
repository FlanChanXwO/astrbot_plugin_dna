"""Goal 2 / Task 11：别名管理 API 契约。

旧版自定义面板管理已经从服务和 Dashboard 移除；本文件只保留别名管理覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.admin import AdminAliasCatalog, AdminAliasService


def _alias_service(tmp_path: Path) -> tuple[AdminAliasService, Path, str, str]:
    alias_dir = tmp_path / "resources" / "alias"
    alias_dir.mkdir(parents=True)
    default_path = alias_dir / "char_alias.json"
    default_path.write_text(
        json.dumps(
            {"角色甲": ["甲", "小甲"], "角色乙": ["乙"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    weapon_path = alias_dir / "weapon_alias.json"
    weapon_path.write_text(json.dumps({"武器甲": ["甲武"]}), encoding="utf-8")
    custom_path = tmp_path / "alias_custom.json"
    custom_path.write_text('{"角色甲": ["自定义甲"]}', encoding="utf-8")
    return (
        AdminAliasService(
            default_path,
            custom_path=custom_path,
            weapon_alias_path=weapon_path,
        ),
        default_path,
        default_path.read_text(encoding="utf-8"),
        custom_path.read_text(encoding="utf-8"),
    )


@pytest.mark.asyncio
async def test_alias_admin_exposes_default_and_custom_without_mutating_defaults(
    tmp_path: Path,
) -> None:
    service, default_path, default_text, _custom_text = _alias_service(tmp_path)

    response = await service.list_aliases()

    assert response.ok is True
    assert isinstance(response.data, AdminAliasCatalog)
    assert response.data is not None
    role = response.data.role("角色甲")
    assert role is not None
    assert role.default_aliases == ("甲", "小甲")
    assert role.custom_aliases == ("自定义甲",)
    assert role.effective_aliases == ("甲", "小甲", "自定义甲")
    weapon = response.data.weapon("武器甲")
    assert weapon is not None and weapon.default_aliases == ("甲武",)
    assert default_path.read_text(encoding="utf-8") == default_text


def test_resource_store_merges_runtime_custom_aliases_after_reload(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    default_path = resource_root / "alias" / "char_alias.json"
    default_path.parent.mkdir(parents=True)
    default_path.write_text('{"角色甲": ["甲"]}', encoding="utf-8")
    (tmp_path / "alias_custom.json").write_text(
        '{"角色甲": ["新甲"]}',
        encoding="utf-8",
    )

    store = EncyclopediaResourceStore.from_root(resource_root)

    assert store.aliases.resolve_char("新甲") == "角色甲"
    assert store.aliases.char_alias_list("角色甲") == ("甲", "新甲")


@pytest.mark.asyncio
async def test_alias_admin_validates_duplicates_and_supports_weapon_layer(
    tmp_path: Path,
) -> None:
    service, default_path, default_text, _custom_text = _alias_service(tmp_path)

    added = await service.add_alias("角色甲", "新甲")
    assert added.ok is True
    duplicate = await service.add_alias("角色甲", "  新甲  ")
    assert duplicate.ok is False
    assert duplicate.error is not None and duplicate.error.code.value == "conflict"
    default_collision = await service.add_alias("角色甲", "甲")
    assert default_collision.ok is False
    assert (
        default_collision.error is not None
        and default_collision.error.code.value == "conflict"
    )

    weapon_added = await service.add_weapon_alias("武器甲", "新武器")
    assert weapon_added.ok is True
    weapon_catalog = await service.list_aliases()
    assert weapon_catalog.data is not None
    assert weapon_catalog.data.weapon("武器甲").custom_aliases == ("新武器",)  # type: ignore[union-attr]
    assert default_path.read_text(encoding="utf-8") == default_text


@pytest.mark.asyncio
async def test_alias_admin_deletes_custom_and_recovers_without_touching_defaults(
    tmp_path: Path,
) -> None:
    service, default_path, default_text, _custom_text = _alias_service(tmp_path)

    assert (await service.delete_alias("角色甲", "甲")).ok is False
    assert (await service.add_alias("角色乙", "自定义乙")).ok is True
    assert (await service.delete_alias("角色甲", "自定义甲")).ok is True
    assert (await service.restore_role("角色乙")).ok is True
    assert (await service.restore_all()).ok is True

    catalog = await service.list_aliases()
    assert catalog.data is not None
    assert catalog.data.role("角色甲").custom_aliases == ()  # type: ignore[union-attr]
    assert catalog.data.role("角色乙").custom_aliases == ()  # type: ignore[union-attr]
    assert catalog.data.weapon("武器甲").custom_aliases == ()  # type: ignore[union-attr]
    assert default_path.read_text(encoding="utf-8") == default_text


@pytest.mark.asyncio
async def test_alias_admin_atomic_write_failure_preserves_previous_custom_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _default_path, _default_text, custom_text = _alias_service(tmp_path)
    custom_path = service.custom_path
    original_replace = Path.replace

    def fail_replace(self: Path, target: str | Path) -> Path:
        if Path(target) == custom_path:
            raise OSError("read-only custom layer")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    failed = await service.add_alias("角色甲", "不会写入")

    assert failed.ok is False
    assert failed.error is not None and failed.error.code.value == "internal"
    assert custom_path.read_text(encoding="utf-8") == custom_text
    assert not custom_path.with_name(f".{custom_path.name}.tmp").exists()


def test_build_runtime_wires_alias_service_without_panel_service(tmp_path: Path) -> None:
    from src.bootstrap import build_runtime

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    assert isinstance(runtime.services["admin_alias_service"], AdminAliasService)
    assert "admin_panel_service" not in runtime.services
    assert "panel_service" not in runtime.services
    assert runtime.services["admin_alias_service"].custom_path == tmp_path / "alias_custom.json"  # type: ignore[union-attr]
