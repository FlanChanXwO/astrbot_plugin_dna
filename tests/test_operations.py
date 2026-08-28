"""Task 25 面板图管理与资源状态的隔离 fixture 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.entry.response import ChainResponse, ImageResponse, PlainTextResponse
from src.modules.operations import messages
from src.modules.operations.service import PanelCommandRequest, PanelService


def _service(tmp_path: Path) -> PanelService:
    return PanelService(
        tmp_path / "panel_custom",
        resource_root=tmp_path / "resources",
        resolve_char_id=lambda name: {"角色甲": "101"}.get(name),
        panel_dir_for=lambda char_id: f"role-{char_id}",
    )


def _request(
    text: str, parameters: dict | None = None, images: tuple[str, ...] = ()
) -> PanelCommandRequest:
    return PanelCommandRequest(
        actor=EventActor("user-1", "bot-1", "group-1"),
        parameters=parameters or {},
        text=text,
        images=images,
    )


def _png(tmp_path: Path, name: str = "panel.png", color: str = "purple") -> Path:
    path = tmp_path / name
    Image.new("RGBA", (37, 53), color).save(path)
    return path


def _panel_dir(tmp_path: Path) -> Path:
    return tmp_path / "panel_custom" / "role-101"


@pytest.mark.asyncio
async def test_upload_panel_img_saves_webp_and_reports_count(tmp_path: Path) -> None:
    """上传保存 WebP 到角色面板目录并报告张数。"""

    service = _service(tmp_path)
    source = _png(tmp_path)

    response = await service.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"}, images=(str(source),)),
    )

    assert isinstance(response, PlainTextResponse)
    assert "已上传角色甲面板图1张" in response.text
    files = list(_panel_dir(tmp_path).iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".webp"
    await service.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"}, images=(str(source),)),
    )
    assert len(list(_panel_dir(tmp_path).iterdir())) == 1  # 相同内容去重（sha1 相同）


@pytest.mark.asyncio
async def test_upload_requires_image(tmp_path: Path) -> None:
    """无图片返回显式提示。"""

    service = _service(tmp_path)
    response = await service.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"})
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.PANEL_IMAGE_REQUIRED


@pytest.mark.asyncio
async def test_upload_unknown_char_is_visible(tmp_path: Path) -> None:
    """未知角色返回显式别名错误。"""

    service = _service(tmp_path)
    response = await service.upload_panel_img(
        _request(
            "上传不存在面板图", {"char_name": "不存在"}, images=(str(_png(tmp_path)),)
        ),
    )

    assert isinstance(response, PlainTextResponse)
    assert "角色别名【不存在】" in response.text


@pytest.mark.asyncio
async def test_upload_bad_bytes_counts_failure(tmp_path: Path) -> None:
    """非法图像字节计为失败，不静默伪造成功。"""

    service = _service(tmp_path)
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not an image")
    response = await service.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"}, images=(str(bad),)),
    )

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.PANEL_UPLOAD_FAILED


@pytest.mark.asyncio
async def test_list_panel_imgs_returns_chain_with_images(tmp_path: Path) -> None:
    """面板图列表返回文本标题与图片链。"""

    service = _service(tmp_path)
    await service.upload_panel_img(
        _request(
            "上传角色甲面板图", {"char_name": "角色甲"}, images=(str(_png(tmp_path)),)
        ),
    )

    response = await service.list_panel_imgs(
        _request("角色甲面板图列表", {"char_name": "角色甲"})
    )

    assert isinstance(response, ChainResponse)
    components = response.components
    assert any("角色甲面板图列表：共1张" in getattr(c, "text", "") for c in components)
    assert any(isinstance(c, ImageResponse) for c in components)


@pytest.mark.asyncio
async def test_delete_panel_img_by_id(tmp_path: Path) -> None:
    """按 ID 删除面板图；未找到显式提示。"""

    service = _service(tmp_path)
    await service.upload_panel_img(
        _request(
            "上传角色甲面板图", {"char_name": "角色甲"}, images=(str(_png(tmp_path)),)
        ),
    )
    image_id = next(_panel_dir(tmp_path).iterdir()).stem

    ok = await service.delete_panel_img_by_id(
        _request("删除角色甲面板图x", {"char_name": "角色甲", "image_id": image_id}),
    )
    missing = await service.delete_panel_img_by_id(
        _request("删除角色甲面板图x", {"char_name": "角色甲", "image_id": "missing"}),
    )

    assert isinstance(ok, PlainTextResponse)
    assert "已删除角色甲面板图" in ok.text
    assert (
        not _panel_dir(tmp_path).exists() or list(_panel_dir(tmp_path).iterdir()) == []
    )
    assert isinstance(missing, PlainTextResponse)
    assert (
        messages.PANEL_DELETED_NOT_FOUND.format(name="角色甲", image_id="missing")
        in missing.text
    )


@pytest.mark.asyncio
async def test_delete_all_panel_imgs_removes_directory(tmp_path: Path) -> None:
    """删除全部面板图移除目录。"""

    service = _service(tmp_path)
    await service.upload_panel_img(
        _request(
            "上传角色甲面板图", {"char_name": "角色甲"}, images=(str(_png(tmp_path)),)
        ),
    )

    response = await service.delete_all_panel_imgs(
        _request("删除角色甲全部面板图", {"char_name": "角色甲"})
    )

    assert isinstance(response, PlainTextResponse)
    assert "已删除角色甲全部面板图：1张" in response.text
    assert not _panel_dir(tmp_path).exists()


@pytest.mark.asyncio
async def test_delete_original_panel_img_reports_unsupported(tmp_path: Path) -> None:
    """原图删除在公开结果边界显式报告不支持。"""

    service = _service(tmp_path)
    response = await service.delete_original_panel_img(_request("原图删除"))

    assert isinstance(response, PlainTextResponse)
    assert response.text == messages.PANEL_ORIGINAL_UNSUPPORTED


@pytest.mark.asyncio
async def test_compress_panel_imgs(tmp_path: Path) -> None:
    """压缩面板图把 PNG 转为 WebP 并报告数量。"""

    service = _service(tmp_path)
    source = _png(tmp_path)
    await service.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"}, images=(str(source),)),
    )
    # 直接放一张非 webp 的面板图用于压缩计数
    extra = _panel_dir(tmp_path) / "extra.png"
    Image.new("RGB", (17, 19), "green").save(extra)

    response = await service.compress_panel_imgs(_request("压缩面板图"))

    assert isinstance(response, PlainTextResponse)
    assert "压缩完成" in response.text
    assert any(p.suffix == ".webp" for p in _panel_dir(tmp_path).iterdir())


@pytest.mark.asyncio
async def test_resource_status_reports_manifest_state(tmp_path: Path) -> None:
    """资源状态展示 manifest 与目录信息。"""

    service = _service(tmp_path)
    empty = await service.resource_status(_request("资源状态"))
    assert isinstance(empty, PlainTextResponse)
    assert messages.RESOURCE_STATUS_EMPTY in empty.text

    resource_root = tmp_path / "resources"
    resource_root.mkdir(parents=True)
    (resource_root / "resource_manifest.json").write_text(
        '{"format_version": 1, "required_dirs": ["fonts", "panel"], "resource_version": "1.0"}',
        encoding="utf-8",
    )
    (resource_root / "fonts").mkdir()
    service2 = PanelService(
        tmp_path / "panel_custom",
        resource_root=resource_root,
        resolve_char_id=lambda name: "101",
        panel_dir_for=lambda char_id: "role-101",
    )
    with_status = await service2.resource_status(_request("资源状态"))
    assert "manifest: v1" in with_status.text
    assert "必需目录: 1/2 存在" in with_status.text


@pytest.mark.asyncio
async def test_upload_rejects_path_escaping_char_id(tmp_path: Path) -> None:
    """角色目录解析越界时拒绝写入，不逃逸 panel_root。"""

    evil = PanelService(
        tmp_path / "panel_custom",
        resource_root=tmp_path / "resources",
        resolve_char_id=lambda name: {"角色甲": "101"}.get(name),
        panel_dir_for=lambda char_id: "../escape",
    )
    source = _png(tmp_path)

    response = await evil.upload_panel_img(
        _request("上传角色甲面板图", {"char_name": "角色甲"}, images=(str(source),)),
    )

    assert isinstance(response, PlainTextResponse)
    assert "角色别名【角色甲】" in response.text
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "panel_custom" / ".." / "escape").exists()


@pytest.mark.asyncio
async def test_alias_add_delete_and_recover(tmp_path: Path) -> None:
    """别名写入在隔离目录 fixture 中可增删并刷新。"""

    refreshed = []
    from src.modules.operations.alias_service import AliasService

    alias_root = tmp_path / "alias"
    alias_root.mkdir()
    (alias_root / "char_alias.json").write_text('{"辛西娅": []}', encoding="utf-8")
    service = AliasService(alias_root, refresh=lambda: refreshed.append(True))
    add = await service.add_delete_alias(
        _request(
            "添加角色辛西娅别名小辛",
            {
                "action": "添加",
                "alias_type": "角色",
                "name": "辛西娅",
                "new_alias": "小辛",
            },
        ),
    )
    dup = await service.add_delete_alias(
        _request(
            "添加角色辛西娅别名小辛",
            {
                "action": "添加",
                "alias_type": "角色",
                "name": "辛西娅",
                "new_alias": "小辛",
            },
        ),
    )
    delete = await service.add_delete_alias(
        _request(
            "删除角色辛西娅别名小辛",
            {
                "action": "删除",
                "alias_type": "角色",
                "name": "辛西娅",
                "new_alias": "小辛",
            },
        ),
    )
    missing = await service.add_delete_alias(
        _request(
            "删除角色辛西娅别名小辛",
            {
                "action": "删除",
                "alias_type": "角色",
                "name": "辛西娅",
                "new_alias": "小辛",
            },
        ),
    )
    recover = await service.recover_alias(None)

    assert messages.ALIAS_ADDED.format(name="辛西娅", alias="小辛") in add.text
    assert messages.ALIAS_DUPLICATE.format(name="辛西娅", alias="小辛") in dup.text
    assert messages.ALIAS_DELETED.format(name="辛西娅", alias="小辛") in delete.text
    assert messages.ALIAS_NOT_FOUND.format(name="辛西娅", alias="小辛") in missing.text
    assert recover.text == messages.ALIAS_RECOVERED
    assert len(refreshed) == 3  # 添加 + 删除 + 恢复各刷新一次
    assert (tmp_path / "alias_custom.json").exists()


@pytest.mark.asyncio
async def test_alias_input_empty_is_visible(tmp_path: Path) -> None:
    """别名名称/别名为空返回显式提示。"""

    from src.modules.operations.alias_service import AliasService

    service = AliasService(tmp_path / "alias")
    response = await service.add_delete_alias(
        _request(
            "添加角色别名",
            {"action": "添加", "alias_type": "角色", "name": "", "new_alias": ""},
        ),
    )
    assert response.text == messages.ALIAS_INPUT_EMPTY
