"""Goal 2 / Task 11：面板图与角色别名管理 API 契约。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.infrastructure.persistence import AsyncDatabase
from src.infrastructure.resources import EncyclopediaResourceStore
from src.modules.admin import (
    AdminAliasCatalog,
    AdminAliasService,
    AdminPanelService,
    PanelCompressionResult,
    PanelImage,
    PanelImageMetadata,
)
from src.modules.operations.service import PanelService


def _panel_service(tmp_path: Path, *, panel_dir_for=None) -> PanelService:
    return PanelService(
        tmp_path / "panel_custom",
        resource_root=tmp_path / "resources",
        resolve_char_id=lambda name: {"角色甲": "101"}.get(name),
        panel_dir_for=panel_dir_for or (lambda char_id: f"role-{char_id}"),
    )


def _png_bytes(color: str = "purple") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (96, 128), color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_panel_admin_lists_metadata_and_reads_image_on_demand(
    tmp_path: Path,
) -> None:
    service = AdminPanelService(_panel_service(tmp_path))

    uploaded = await service.upload_panel_image("角色甲", _png_bytes())

    assert uploaded.ok is True
    assert isinstance(uploaded.data, PanelImageMetadata)
    image_id = uploaded.data.id
    listed = await service.list_panel_images("角色甲")
    assert listed.ok is True
    assert listed.data is not None and listed.data[0].id == image_id
    assert str(tmp_path) not in repr(listed.data[0])
    assert "path" not in listed.data[0].to_dict()

    loaded = await service.get_panel_image("角色甲", image_id)
    assert loaded.ok is True
    assert isinstance(loaded.data, PanelImage)
    assert loaded.data.data.startswith(b"RIFF")
    assert loaded.data.media_type == "image/webp"
    assert str(tmp_path) not in repr(loaded.data)


@pytest.mark.asyncio
async def test_panel_admin_rejects_path_escape_and_unknown_role(tmp_path: Path) -> None:
    escaping = AdminPanelService(
        _panel_service(tmp_path, panel_dir_for=lambda _char_id: "../escape"),
    )
    rejected = await escaping.upload_panel_image("角色甲", _png_bytes())
    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error.code.value in {"validation", "not_found"}
    assert not (tmp_path / "escape").exists()

    service = AdminPanelService(_panel_service(tmp_path))
    unknown = await service.list_panel_images("不存在")
    assert unknown.ok is False
    assert unknown.error is not None and unknown.error.code.value == "not_found"
    invalid_id = await service.get_panel_image("角色甲", "../escape")
    assert invalid_id.ok is False
    assert invalid_id.error is not None and invalid_id.error.code.value == "validation"


@pytest.mark.asyncio
async def test_panel_admin_delete_all_requires_confirmation_and_compresses(
    tmp_path: Path,
) -> None:
    backend = _panel_service(tmp_path)
    service = AdminPanelService(backend)
    uploaded = await service.upload_panel_image("角色甲", _png_bytes())
    assert uploaded.ok is True

    refused = await service.delete_all_panel_images("角色甲")
    assert refused.ok is False
    assert refused.error is not None and refused.error.code.value == "validation"
    refused_non_bool = await service.delete_all_panel_images(
        "角色甲",
        confirmed="false",  # type: ignore[arg-type]
    )
    assert refused_non_bool.ok is False
    assert (
        refused_non_bool.error is not None
        and refused_non_bool.error.code.value == "validation"
    )
    assert (await service.list_panel_images("角色甲")).data

    deleted = await service.delete_all_panel_images("角色甲", confirmed=True)
    assert deleted.ok is True
    assert (await service.list_panel_images("角色甲")).data == ()

    panel_dir = backend.panel_root / "role-101"
    panel_dir.mkdir(parents=True)
    Image.new("RGB", (640, 640), "green").save(panel_dir / "extra.png")
    compressed = await service.compress_panel_images()
    assert compressed.ok is True
    assert isinstance(compressed.data, PanelCompressionResult)
    assert compressed.data.total == 1


def _alias_service(tmp_path: Path) -> tuple[AdminAliasService, Path, str, str]:
    default_path = tmp_path / "resources" / "alias" / "char_alias.json"
    default_path.parent.mkdir(parents=True)
    default_path.write_text(
        json.dumps(
            {"角色甲": ["甲", "小甲"], "角色乙": ["乙"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    custom_path = tmp_path / "alias_custom.json"
    custom_path.write_text('{"角色甲": ["自定义甲"]}', encoding="utf-8")
    return (
        AdminAliasService(default_path, custom_path=custom_path),
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
    assert default_path.read_text(encoding="utf-8") == default_text


def test_resource_store_merges_runtime_custom_aliases_after_reload(
    tmp_path: Path,
) -> None:
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
async def test_alias_admin_validates_duplicates_defaults_and_cross_role_conflicts(
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
    cross_role = await service.add_alias("角色乙", "新甲")
    assert cross_role.ok is False
    assert cross_role.error is not None and cross_role.error.code.value == "conflict"
    empty = await service.add_alias("角色甲", "  ")
    assert empty.ok is False
    assert empty.error is not None and empty.error.code.value == "validation"
    unknown = await service.add_alias("不存在", "新别名")
    assert unknown.ok is False
    assert unknown.error is not None and unknown.error.code.value == "not_found"
    assert default_path.read_text(encoding="utf-8") == default_text


@pytest.mark.asyncio
async def test_alias_admin_only_deletes_custom_and_restores_role_or_all(
    tmp_path: Path,
) -> None:
    service, default_path, default_text, _custom_text = _alias_service(tmp_path)

    default_delete = await service.delete_alias("角色甲", "甲")
    assert default_delete.ok is False
    assert (
        default_delete.error is not None
        and default_delete.error.code.value == "conflict"
    )
    added = await service.add_alias("角色乙", "自定义乙")
    assert added.ok is True
    deleted = await service.delete_alias("角色甲", "自定义甲")
    assert deleted.ok is True
    restored_role = await service.restore_role("角色乙")
    assert restored_role.ok is True
    restored_all = await service.restore_all()
    assert restored_all.ok is True
    catalog = await service.list_aliases()
    assert catalog.data is not None
    role_a = catalog.data.role("角色甲")
    role_b = catalog.data.role("角色乙")
    assert role_a is not None and role_a.custom_aliases == ()
    assert role_b is not None and role_b.custom_aliases == ()
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


def test_build_runtime_wires_task11_admin_services(tmp_path: Path) -> None:
    from src.bootstrap import build_runtime

    runtime = build_runtime(
        SimpleNamespace(register_web_api=lambda *args: None),
        {},
        database=AsyncDatabase(tmp_path / "dnaby.sqlite3"),
    )

    assert isinstance(runtime.services["admin_panel_service"], AdminPanelService)
    assert isinstance(runtime.services["admin_alias_service"], AdminAliasService)
    assert (
        runtime.services["admin_alias_service"].custom_path
        == tmp_path / "alias_custom.json"
    )  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_legacy_alias_service_uses_custom_layer_when_configured(
    tmp_path: Path,
) -> None:
    from src.modules.operations.alias_service import AliasService

    alias_root = tmp_path / "resources" / "alias"
    alias_root.mkdir(parents=True)
    default_path = alias_root / "char_alias.json"
    default_path.write_text('{"角色甲": ["甲"]}', encoding="utf-8")
    custom_path = tmp_path / "alias_custom.json"
    custom_path.write_text("{}", encoding="utf-8")
    default_text = default_path.read_text(encoding="utf-8")

    service = AliasService(alias_root, custom_path=custom_path)
    response = await service.add_delete_alias(
        SimpleNamespace(
            parameters={
                "action": "添加",
                "alias_type": "角色",
                "name": "角色甲",
                "new_alias": "新甲",
            },
        ),
    )

    assert response.text == "已添加别名【角色甲】→ 新甲"
    assert default_path.read_text(encoding="utf-8") == default_text
    assert json.loads(custom_path.read_text(encoding="utf-8")) == {"角色甲": ["新甲"]}


@pytest.mark.asyncio
async def test_legacy_alias_service_defaults_to_custom_layer(tmp_path: Path) -> None:
    from src.modules.operations.alias_service import AliasService

    alias_root = tmp_path / "resources" / "alias"
    alias_root.mkdir(parents=True)
    default_path = alias_root / "char_alias.json"
    default_path.write_text('{"角色甲": ["甲"]}', encoding="utf-8")
    default_text = default_path.read_text(encoding="utf-8")

    service = AliasService(alias_root)
    response = await service.add_delete_alias(
        SimpleNamespace(
            parameters={
                "action": "添加",
                "alias_type": "角色",
                "name": "角色甲",
                "new_alias": "默认也不应被改",
            },
        ),
    )

    assert response.text == "已添加别名【角色甲】→ 默认也不应被改"
    assert default_path.read_text(encoding="utf-8") == default_text
    assert json.loads(
        (tmp_path / "resources" / "alias_custom.json").read_text(encoding="utf-8")
    ) == {"角色甲": ["默认也不应被改"]}
