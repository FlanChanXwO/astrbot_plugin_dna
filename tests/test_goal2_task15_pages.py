import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
PAGE_ROOT = PROJECT_ROOT / "pages" / "dashboard"


def _page_files() -> tuple[str, str, str]:
    return (
        (PAGE_ROOT / "index.html").read_text(encoding="utf-8"),
        (PAGE_ROOT / "js" / "store.js").read_text(encoding="utf-8"),
        (PAGE_ROOT / "js" / "bridge.js").read_text(encoding="utf-8"),
    )


def _factory(bridge: str) -> str:
    return bridge.split("export function createDashboardApi()", 1)[1].split(
        "export async function getAliasCatalog", 1
    )[0]


def test_account_page_has_global_collapsed_list_and_plaintext_editor_contract() -> None:
    html, store, bridge = _page_files()

    assert 'data-page="accounts"' in html
    assert "账号与预览" in html
    assert "accountGroups" in html or "accountGroups" in store
    assert "accountsLoading" in html
    assert "include_credentials" in bridge
    assert "credentials" in html
    for field in (
        "user_id",
        "uid",
        "group_id",
        "is_active",
        "app_cookie",
        "app_device_code",
        "app_d_num",
        "app_refresh_token",
        "app_status",
        "web_token",
        "web_device_code",
        "web_d_num",
        "web_refresh_token",
        "web_status",
    ):
        assert field in html
    assert "readonly" in html
    assert "openAccountEditor" in html
    assert "clearAccountSecrets" in store
    assert "closeAccountEditor" in store
    assert "includeCredentials: false" in store


def test_account_bridge_and_store_cover_preview_and_two_phase_deletion() -> None:
    html, store, bridge = _page_files()
    factory = _factory(bridge)

    for method in (
        "getAccounts",
        "getAccount",
        "updateAccount",
        "getUidDeletePreview",
        "deleteUid",
        "getUserDeletePreview",
        "deleteUser",
        "previewOverview",
        "previewDetail",
    ):
        assert re.search(rf"^\s*{method}(?::\s*{method})?,?\s*$", factory, re.MULTILINE)
        assert method in bridge
        assert method in store or method in html

    assert "delete-preview" in bridge
    assert "confirmation_payload" in bridge
    assert "accountDeletePlan" in store
    assert "confirmDeleteUid" in html
    assert "confirmDeleteUser" in html
    assert "previewOverview" in html
    assert "previewDetail" in html
    assert "reloadAccountState" in store
    assert "await this.reloadAccountState()" in store


def test_preview_overlay_is_memory_only_and_clears_secrets_and_image_references() -> (
    None
):
    html, store, bridge = _page_files()

    assert "accountPreview" in html
    assert "previewImageUrl" in html
    assert "data_base64" in store or "data_base64" in bridge
    assert "clearPreviewState" in store
    assert "clearAccountSecrets" in store
    assert "selectedAccount = null" in store
    assert "closeDrawer" in store
    assert "previewCharName" in html
    assert "previewWeaponNames" in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "localStorage" not in store
    assert "sessionStorage" not in store
    assert "localStorage" not in bridge
    assert "sessionStorage" not in bridge


def test_alias_page_separates_readonly_defaults_from_multiple_custom_values() -> None:
    html, store, bridge = _page_files()
    factory = _factory(bridge)

    assert 'data-page="aliases"' in html
    for field in (
        "aliasRoles",
        "default_aliases",
        "custom_aliases",
        "effective_aliases",
        "aliasDrafts",
        "confirmAddAlias",
        "confirmDeleteAlias",
        "confirmRestoreAlias",
        "confirmRestoreAllAliases",
    ):
        assert field in html or field in store
    for method in (
        "addAlias",
        "deleteAlias",
        "restoreAliasRole",
        "restoreAllAliases",
    ):
        assert re.search(rf"^\s*{method}(?::\s*{method})?,?\s*$", factory, re.MULTILINE)
        assert method in bridge
        assert method in store or method in html

    assert "自定义别名" in html
    assert "默认别名" in html
    assert "恢复默认" in html
    assert "weapon_alias" not in html
    assert "武器别名" not in html


def test_account_and_alias_writes_reload_server_truth_and_use_confirmations() -> None:
    html, store, _bridge = _page_files()

    assert "confirmSaveAccount" in html
    assert "confirmAddAlias" in html
    assert "confirmDeleteAlias" in html
    assert "confirmRestoreAlias" in html
    assert "confirmRestoreAllAliases" in html
    assert "reloadAliasState" in store
    assert "await this.reloadAliasState()" in store
    assert "await this.api.updateAccount" in store
    assert "await this.api.addAlias" in store
    assert "await this.api.deleteAlias" in store
    assert "await this.api.restoreAliasRole" in store
    assert "await this.api.restoreAllAliases" in store


def test_alias_markup_only_offers_delete_for_custom_aliases() -> None:
    html, _store, _bridge = _page_files()

    assert re.search(
        r"custom_aliases[\s\S]{0,900}confirmDeleteAlias",
        html,
    )
    assert "role.default_aliases" in html
    assert "alias-tags--readonly" in html
