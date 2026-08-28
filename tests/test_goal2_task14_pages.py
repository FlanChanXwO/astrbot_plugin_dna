import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
PAGE_ROOT = PROJECT_ROOT / "pages" / "dashboard"


def test_panel_page_has_search_lazy_images_and_confirmed_file_actions() -> None:
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")
    bridge = (PAGE_ROOT / "js" / "bridge.js").read_text(encoding="utf-8")
    factory = bridge.split("export function createDashboardApi()", 1)[1].split(
        "export async function getAliasCatalog", 1
    )[0]

    assert 'data-page="panels"' in html
    assert "角色面板图" in html
    assert "panelSearch" in html
    assert "filteredPanels" in html
    assert "panel-thumbnail" in html
    assert "panelImageUrl" in html
    assert "prepareUploadPanel" in html
    assert "confirmDeletePanel" in html
    assert "confirmDeleteAllPanels" in html
    assert "confirmCompressPanels" in html
    assert "openDialog" in store
    assert "confirmDeleteAllPanels" in store
    assert "getPanelImages" in bridge
    assert "getPanelImage" in bridge
    assert "uploadPanel" in bridge
    assert "deleteAllPanels" in bridge
    assert "compressPanels" in bridge
    for method in (
        "getAliasCatalog",
        "getPanelImages",
        "getPanelImage",
        "uploadPanel",
        "deletePanel",
        "deleteAllPanels",
        "compressPanels",
        "getTasks",
        "getTargets",
        "updateTask",
        "pauseTask",
        "resumeTask",
        "deleteTask",
        "getMembershipCapability",
        "scanMembers",
        "cleanupMemberGroup",
        "getMemberDeletePreview",
        "deleteMemberUser",
    ):
        assert re.search(rf"^\s*{method}(?::\s*{method})?,?\s*$", factory, re.MULTILINE)


def test_task_page_shows_schedule_next_run_targets_and_safe_actions() -> None:
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")
    bridge = (PAGE_ROOT / "js" / "bridge.js").read_text(encoding="utf-8")

    assert 'data-page="tasks"' in html
    assert "任务与探测" in html
    assert "tasksLoading" in html
    assert "task.schedule" in html
    assert "next_run_at" in html
    assert "task.targets" in html
    assert "pauseTask" in html
    assert "resumeTask" in html
    assert "deleteTask" in html
    assert "confirmation_payload" in store
    assert "getTasks" in bridge
    assert "getTargets" in bridge
    assert "updateTask" in bridge
    assert "deleteTask" in bridge
    assert "createTask" not in html
    assert "createTask" not in store
    assert "createTask" not in bridge


def test_membership_page_disables_unsupported_platform_and_requires_confirmed_cleanup() -> (
    None
):
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")
    bridge = (PAGE_ROOT / "js" / "bridge.js").read_text(encoding="utf-8")

    assert "membershipCapability" in html
    assert "aiocqhttp" in html
    assert "canScanMembers" in html
    assert ':disabled="!canScanMembers"' in html
    assert "scanMembers" in html
    assert "present" in html
    assert "absent" in html
    assert "unknown" in html
    assert "confirmCleanup" in html
    assert "confirmDeleteMemberUser" in html
    assert "confirmCleanup" in store
    assert "confirmDeleteMemberUser" in store
    assert "getMembershipCapability" in bridge
    assert "scanMembers" in bridge
    assert "cleanupMemberGroup" in bridge
    assert "deleteMemberUser" in bridge


def test_task14_writes_enter_confirmation_before_mutating_state() -> None:
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")

    assert "prepareUploadPanel" in html
    assert "confirmTaskSchedule" in html
    assert "confirmTaskSchedule" in store
    assert "pendingPanelFile" in store
    assert "scanMembers(true)" in store


def test_task14_actions_reload_server_state_after_success_and_are_mobile_ready() -> (
    None
):
    html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
    store = (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8")
    css = (PAGE_ROOT / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert "reloadPanelState" in store
    assert "reloadTaskState" in store
    assert "reloadMembershipState" in store
    assert "await this.reloadPanelState()" in store
    assert "await this.reloadTaskState()" in store
    assert "await this.reloadMembershipState()" in store
    assert "panel-grid" in html
    assert "task-list" in html
    assert "membership-results" in html
    assert "@media (max-width: 767px)" in css
    assert "grid-template-columns: 1fr" in css
    assert not re.search(r"\bcreate\s+task\b", html, flags=re.IGNORECASE)
