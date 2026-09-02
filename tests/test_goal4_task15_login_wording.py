"""Goal 4 / Task 15：登录与 UID 管理文案边界。"""

from __future__ import annotations

import json
from pathlib import Path

from src.entry.commands import load_command_registry, manifest_records
from src.modules.checkin import messages as checkin_messages
from src.modules.encyclopedia import messages as encyclopedia_messages
from src.modules.player import messages as player_messages

ROOT = Path(__file__).parents[1]


def test_query_failures_ask_for_login_not_uid_rebinding() -> None:
    values = [
        player_messages.PLAYER_UID_INVALID,
        checkin_messages.CHECKIN_UID_INVALID,
        encyclopedia_messages.UID_INVALID,
        "登录已失效，请重新登录",
        __import__(
            "src.modules.notices.messages", fromlist=["NOTICES_UID_INVALID"]
        ).NOTICES_UID_INVALID,
    ]
    assert all(
        "重新绑定" not in value and "请先绑定账号" not in value for value in values
    )
    assert all("登录" in value for value in values)


def test_login_page_and_help_use_login_wording_without_uid_binding_command() -> None:
    template = (ROOT / "src/templates/index.html.j2").read_text()
    help_data = json.loads((ROOT / "src/resources/help/help.json").read_text())
    account_names = [item["name"] for item in help_data["账号管理"]["data"]]
    assert "<h1>登录 DNAUID</h1>" in template
    assert "在执行查询之前请先登录" in help_data["账号管理"]["desc"]
    assert "token登录" in account_names
    assert "绑定UID" not in account_names


def test_commands_manifest_matches_registry_and_account_group_is_account_management() -> (
    None
):
    registry = load_command_registry()
    manifest = json.loads((ROOT / "commands.json").read_text())
    assert manifest == manifest_records(registry)
    assert registry.get("account_login").group == "账号管理"
    assert registry.get("account_token_login").group == "账号管理"
    assert "account_bind" not in {spec.id for spec in registry}
