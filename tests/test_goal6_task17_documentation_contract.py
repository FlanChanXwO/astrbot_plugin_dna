"""Goal 6 / Task 17：公开文档与配置、命令投影的一致性契约。"""

from __future__ import annotations

import json
from pathlib import Path

from src.entry.commands import load_command_registry, manifest_records
from src.infrastructure.config.schema import generate_astrbot_schema

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_generated_config_and_command_projections_are_current() -> None:
    """机器可读投影必须继续由当前 registry/schema 生成。"""

    commands = json.loads(_text("commands.json"))
    schema = json.loads(_text("_conf_schema.json"))

    assert commands == manifest_records(load_command_registry())
    assert schema == generate_astrbot_schema()
    assert len(commands) == 63
    assert set(schema) == {
        "general",
        "login",
        "ai",
        "sign_in",
        "notifications",
        "client_updates",
        "display",
        "network",
        "resources",
        "cache",
    }


def test_public_docs_describe_current_config_and_client_update_contract() -> None:
    """README、usage、project 和维护文档不得把迁移前语义当作当前配置。"""

    readme = _text("README.md")
    configuration = _text("docs/usage/configuration.md")
    commands = _text("docs/usage/commands.md")
    resources = _text("docs/usage/resources.md")
    architecture = _text("docs/project/architecture.md")
    data_model = _text("docs/project/data-model.md")
    maintenance = _text("docs/dev/maintenance.md")
    design = _text("docs/superpowers/specs/2026-09-02-client-updates-design.md")

    assert "配置分为以下十组" in readme
    assert "general.command_prefixes" in readme
    assert "network.proxy_url" in readme
    assert "sign_in.default_auto_sign_enabled" in readme
    assert "client_updates.enabled" in readme
    assert "schema_version: 3" in readme
    assert "完整的 63 条命令" in readme

    for stale_field in (
        "display.command_prefixes",
        "network.api_proxy_url",
        "network.local_proxy_url",
        "network.proxy_functions",
        "network.no_proxy_functions",
        "sign_in.enable_all_users",
        "sign_in.scheduled_enabled",
        "notifications.announcement_ids",
        "notifications.secret_subscriptions",
        "cache.fresh_ttl_minutes",
        "cache.retention_ttl_hours",
        "cache.announcement_ttl_hours",
        "agent_tools.enabled",
    ):
        assert stale_field not in readme

    assert "network.proxy_url" in configuration
    assert "只影响二重螺旋 App REST API 和官方业务 WebSocket" in configuration
    assert "首次无 baseline" in commands
    assert "每个 channel 一个 Node" in commands
    assert "schema_version: 3" in data_model
    assert "region:channel_id" in data_model
    assert "同步资源" in resources
    assert 'StarTools.get_data_dir("astrbot_plugin_dnaby")' in maintenance
    assert "当前 registry 为 63 条" in maintenance
    assert "notifications.client_update_check_minutes" not in architecture
    assert "client_updates.check_minutes" in architecture

    assert "状态：已实现" in design
    assert "region + channel_id" in design
    assert "interval@{client_updates.check_minutes}m" in design
    assert "client_update_enabled" not in design


def test_help_projection_mentions_client_update_commands() -> None:
    """资源帮助在无 registry fallback 时也不能遗漏客户端更新命令。"""

    help_data = json.loads(_text("src/resources/help/help.json"))
    names = [item["name"] for item in help_data["信息查询"]["data"]]

    assert names[-3:] == [
        "客户端更新",
        "订阅客户端更新",
        "取消订阅客户端更新",
    ]
