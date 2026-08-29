"""Goal 2 Task 18：终审发现的日志脱敏与面板删除边界。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.entry.event import EventActor
from src.modules.operations.service import PanelCommandRequest, PanelService

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> PanelService:
    return PanelService(
        tmp_path / "panel_custom",
        resource_root=tmp_path / "resources",
        resolve_char_id=lambda name: {"角色甲": "101"}.get(name),
        panel_dir_for=lambda char_id: f"role-{char_id}",
    )


def _request() -> PanelCommandRequest:
    return PanelCommandRequest(
        actor=EventActor("user-1", "bot-1", "group-1"),
        parameters={"char_name": "角色甲"},
    )


def _panel_with_sentinel(tmp_path: Path) -> tuple[PanelService, Path, Path]:
    service = _service(tmp_path)
    panel_dir = tmp_path / "panel_custom" / "role-101"
    panel_dir.mkdir(parents=True)
    image_path = panel_dir / "panel.png"
    Image.new("RGB", (4, 4), "purple").save(image_path)
    sentinel_path = panel_dir / "managed-by-operator.txt"
    sentinel_path.write_text("保留的非图片文件", encoding="utf-8")
    return service, image_path, sentinel_path


def test_panel_service_removes_only_image_files(tmp_path: Path) -> None:
    """全删面板图不能递归删除同目录中的非图片文件。"""

    service, image_path, sentinel_path = _panel_with_sentinel(tmp_path)

    removed = service.remove_all_panel_files("角色甲")

    assert removed == 1
    assert not image_path.exists()
    assert sentinel_path.exists()


@pytest.mark.asyncio
async def test_legacy_panel_delete_also_preserves_non_image_files(
    tmp_path: Path,
) -> None:
    """旧命令入口与管理 API 使用相同的图片删除边界。"""

    service, image_path, sentinel_path = _panel_with_sentinel(tmp_path)

    response = await service.delete_all_panel_imgs(_request())

    assert "已删除角色甲全部面板图：1张" in response.text
    assert not image_path.exists()
    assert sentinel_path.exists()


@pytest.mark.parametrize(
    "source_path",
    (
        "src/infrastructure/scheduler.py",
        "src/infrastructure/notices_scheduler.py",
        "src/modules/notices/service.py",
    ),
)
def test_push_and_scheduler_logs_do_not_interpolate_exception_details(
    source_path: str,
) -> None:
    """推送异常日志不能把异常原文、会话路由或路径带入日志。"""

    source = (PROJECT_ROOT / source_path).read_text(encoding="utf-8")

    assert "失败: {error}" not in source
    assert "异常: {error}" not in source
    assert "推送至 {origin}" not in source
    assert "发送给 {subscription.unified_msg_origin}" not in source
