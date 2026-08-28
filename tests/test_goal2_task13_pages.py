import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
PAGE_ROOT = PROJECT_ROOT / "pages" / "dashboard"


def test_dashboard_shell_has_required_navigation_and_runtime_assets() -> None:
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    lowered = html.lower()

    assert "<!doctype html>" in lowered
    assert '<html lang="zh-cn">' in lowered
    assert 'name="viewport"' in lowered
    assert 'content="width=device-width, initial-scale=1"' in lowered
    assert "<title>dnaby 管理面板</title>" in lowered
    assert "./lib/petite-vue.iife.js" in html
    assert "./app.js" in html
    assert "./css/dashboard.css" in html
    assert 'id="app"' in html
    assert "v-cloak" in html

    for page_id, label in (
        ("panels", "面板图"),
        ("tasks", "任务与探测"),
        ("accounts", "账号与预览"),
        ("aliases", "角色别名"),
    ):
        assert f'data-page="{page_id}"' in html
        assert label in html

    assert "pluginVersion" in html
    assert "Chart.js" not in html
    assert "chart.js" not in lowered
    assert not re.search(r"\bstats\b", lowered)
    assert "帮助命令" not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html


def test_dashboard_shell_exposes_accessible_overlay_and_mobile_navigation() -> None:
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    css = (PAGE_ROOT / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in html
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'aria-live="polite"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'class="drawer"' in html
    assert ':aria-expanded="mobileNavOpen"' in html
    assert ":class=\"{ 'is-open': mobileNavOpen }\"" in html
    assert ".sidebar.is-open" in css
    assert "@media (max-width: 767px)" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "min-height: 44px" in css


def test_dashboard_bridge_requires_native_astrbot_plugin_page_bridge() -> None:
    bridge = (PAGE_ROOT / "js" / "bridge.js").read_text(encoding="utf-8")

    assert "window.AstrBotPluginPage" in bridge
    assert "AstrBotPluginPage bridge not available" in bridge
    assert "export async function bridgeReady" in bridge
    assert "export async function apiGet" in bridge
    assert "export async function apiPost" in bridge
    assert "export async function apiDelete" in bridge
    assert "localStorage" not in bridge
    assert "sessionStorage" not in bridge


def test_dashboard_app_and_store_mount_petite_vue_without_business_implementation() -> (
    None
):
    app = (PAGE_ROOT / "app.js").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")

    assert "globalThis.PetiteVue" in app
    assert ".createApp" in app
    assert "bridgeReady" in app
    assert "createDashboardStore" in app
    assert "export function createDashboardStore" in store
    assert "activePage" in store
    assert "pluginVersion" in store
    assert "openDialog" in store
    assert "openDrawer" in store
    assert "showToast" in store
    assert "Chart.js" not in app
    assert "Chart.js" not in store


def test_dashboard_vendors_petite_vue_with_license_notice() -> None:
    vendor = PAGE_ROOT / "lib" / "petite-vue.iife.js"
    license_file = PAGE_ROOT / "lib" / "petite-vue.LICENSE.md"

    assert vendor.is_file()
    assert vendor.stat().st_size > 0
    license_text = license_file.read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Evan You" in license_text
    assert "petite-vue" in license_text.lower()


def test_dashboard_page_files_do_not_use_browser_storage_or_chart_runtime() -> None:
    page_files = [path for path in PAGE_ROOT.rglob("*") if path.is_file()]

    assert page_files
    for path in page_files:
        if path.suffix not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "localStorage" not in text
        assert "sessionStorage" not in text
        assert "Chart.js" not in text
        assert "chart.js" not in text.lower()
