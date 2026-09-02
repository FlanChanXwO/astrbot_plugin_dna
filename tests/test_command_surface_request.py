"""命令分组、帮助资源和历史功能保留的发布契约。"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _manifest() -> dict[str, dict[str, object]]:
    records = json.loads((PROJECT_ROOT / "commands.json").read_text(encoding="utf-8"))
    return {record["id"]: record for record in records}


def _help_data() -> dict[str, dict[str, object]]:
    return json.loads(
        (PROJECT_ROOT / "src/resources/help/help.json").read_text(encoding="utf-8"),
    )


def _help_names(help_data: dict[str, dict[str, object]], group: str) -> list[str]:
    return [item["name"] for item in help_data[group]["data"]]


def test_requested_command_surface_and_help_contract() -> None:
    """发布清单不得重新暴露已移除命令，帮助分组必须与新契约一致。"""

    specs = _manifest()

    assert "account_bind" not in specs
    assert not any(spec["group"] == "皎皎角登录" for spec in specs.values())
    assert specs["account_token_login"]["group"] == "账号管理"
    assert specs["account_token_login"]["examples"] == ["kktoken登录<token>"]
    assert specs["account_login"]["examples"] == ["kk登录", "kk登录<token>"]

    privacy_commands = {
        "privacy_enable_peek_admin",
        "privacy_disable_peek_admin",
        "privacy_enable_peek_all",
        "privacy_disable_peek_all",
        "privacy_cancel_peek_all",
        "privacy_enable_uid_hidden_admin",
        "privacy_disable_uid_hidden_admin",
        "privacy_enable_uid_hidden_all",
        "privacy_disable_uid_hidden_all",
        "privacy_cancel_uid_hidden_all",
    }
    assert all(specs[command_id]["group"] == "隐私管理" for command_id in privacy_commands)
    assert all(specs[command_id]["permission"] == "admin" for command_id in privacy_commands)
    assert specs["ann_sub"]["group"] == "公告管理"
    assert specs["ann_unsub"]["group"] == "公告管理"
    assert specs["ann_sub"]["permission"] == "admin"
    assert specs["ann_unsub"]["permission"] == "admin"

    assert specs["resource_status"]["permission"] == "admin"
    assert specs["download_resource"]["permission"] == "admin"

    # 这些是之前已经上线的缓存与新增命令；本次只是整理展示面，不得回滚。
    for command_id in (
        "refresh_all_role_cards",
        "clear_role_cache",
        "clear_player_cache",
        "alias_add_delete",
        "alias_recover",
    ):
        assert command_id in specs

    help_data = _help_data()
    assert "皎皎角登录" not in help_data
    assert "账号登录" not in help_data
    assert "管理员功能" not in help_data
    assert "绑定UID" not in _help_names(help_data, "账号管理")
    assert "token登录" in _help_names(help_data, "账号管理")
    assert _help_names(help_data, "公告管理") == ["订阅公告", "取消订阅公告"]
    assert _help_names(help_data, "资源管理") == ["资源状态", "下载全部资源"]

    order_source = (PROJECT_ROOT / "src/entry/commands/__init__.py").read_text(
        encoding="utf-8",
    )
    assert '"公告管理",' in order_source
    assert '"隐私管理",' in order_source
    assert '"管理员功能",' not in order_source


def test_alias_commands_use_the_bootstrap_alias_service() -> None:
    """别名命令必须调用 bootstrap 实际注入的 AdminAliasService。"""

    commands_source = (PROJECT_ROOT / "src/modules/encyclopedia/commands.py").read_text(
        encoding="utf-8",
    )
    assert 'request.services.get("admin_alias_service")' in commands_source
    assert 'request.services.get("alias_admin_service")' not in commands_source
