"""Goal 2 Task 18：终审发现的日志脱敏与面板移除边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.operations.resource_service import ResourceUpdateService

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_panel_custom_is_preserved_but_not_read_by_resource_status(
    tmp_path: Path,
) -> None:
    """遗留 panel_custom 文件保留，但资源状态服务不再读取或改写它。"""

    panel_custom = tmp_path / "panel_custom"
    panel_custom.mkdir()
    sentinel = panel_custom / "operator-owned.txt"
    sentinel.write_text("保留", encoding="utf-8")

    service = ResourceUpdateService(
        synchronize=lambda: None,
        resource_root=tmp_path / "resources",
    )
    response = await service.status()

    assert str(panel_custom) not in response.text
    assert sentinel.read_text(encoding="utf-8") == "保留"


def test_panel_management_modules_and_routes_are_removed() -> None:
    assert not (PROJECT_ROOT / "src/modules/operations/service.py").exists()
    assert not (PROJECT_ROOT / "src/modules/admin/panels.py").exists()
    admin_web = (PROJECT_ROOT / "src/entry/admin_web.py").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "pages/dashboard/index.html").read_text(encoding="utf-8")
    assert "/panels" not in admin_web
    assert 'data-page="panels"' not in dashboard


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
