"""goal-6 T02：配置重组、迁移和 schema 的 Red 契约。

这些测试只通过 ``DnabySettings.from_config``、``migrate_config_dict`` 和
``generate_astrbot_schema`` 观察配置边界，不锁定内部实现。
"""

from __future__ import annotations

import copy
import logging

import pytest
from pydantic import ValidationError

from src.infrastructure.config.schema import generate_astrbot_schema
from src.infrastructure.config.settings import DnabySettings, migrate_config_dict


def test_goal6_settings_expose_independent_target_groups() -> None:
    """general、ai、client_updates 必须是独立的 typed 配置分组。"""

    settings = DnabySettings.from_config(
        {
            "general": {
                "command_prefixes": ["dna"],
                "allow_mention_query": False,
            },
            "ai": {"agent_tools_enabled": True},
            "client_updates": {
                "enabled": False,
                "check_minutes": 15,
                "channels": ["pc_cn", "android_astc_cn"],
                "merge_forward": False,
            },
            "network": {
                "api_base_url": "https://api.example.test",
                "proxy_url": "http://127.0.0.1:7890",
            },
        },
    )

    assert settings.general.command_prefixes == ["dna"]
    assert settings.general.allow_mention_query is False
    assert settings.ai.agent_tools_enabled is True
    assert settings.client_updates.enabled is False
    assert settings.client_updates.check_minutes == 15
    assert settings.client_updates.channels == ["pc_cn", "android_astc_cn"]
    assert settings.client_updates.merge_forward is False
    assert settings.network.api_base_url == "https://api.example.test"
    assert settings.network.proxy_url == "http://127.0.0.1:7890"
    assert "agent_tools" not in settings.model_dump()


def test_goal6_default_client_channels_are_protocol_ids() -> None:
    """未配置时至少启用计划中的两个固定 channel ID。"""

    settings = DnabySettings.from_config({})

    assert {"pc_cn", "android_astc_cn"}.issubset(
        set(settings.client_updates.channels),
    )


def test_goal6_legacy_client_and_signin_fields_migrate_before_validation() -> None:
    """旧字段必须在进入 Pydantic model_validate 前迁移到新分组。"""

    settings = DnabySettings.from_config(
        {
            "agent_tools": {"enabled": True},
            "notifications": {
                "client_update_enabled": False,
                "client_update_check_minutes": 20,
                "client_update_merge_forward": False,
            },
            "sign_in": {"enable_all_users": False},
        },
    )

    assert settings.ai.agent_tools_enabled is True
    assert settings.client_updates.enabled is False
    assert settings.client_updates.check_minutes == 20
    assert settings.client_updates.merge_forward is False
    assert settings.sign_in.default_auto_sign_enabled is False
    assert "scheduled_enabled" not in settings.sign_in.model_dump()
    assert "enable_all_users" not in settings.sign_in.model_dump()


def test_goal6_network_migration_maps_api_and_safe_proxy_without_mutation() -> None:
    """API base 与满足完整条件的局部代理迁移不能改变调用方输入。"""

    raw = {
        "DNAUrlProxyUrl": "https://api.example.test",
        "network": {
            "api_proxy_url": "https://api.example.test",
            "local_proxy_url": "http://127.0.0.1:7890",
            "proxy_functions": ["all"],
            "no_proxy_functions": [],
        },
    }
    original = copy.deepcopy(raw)

    migrated = migrate_config_dict(raw)

    assert raw == original
    assert migrated["network"]["api_base_url"] == "https://api.example.test"
    assert migrated["network"]["proxy_url"] == "http://127.0.0.1:7890"
    assert "api_proxy_url" not in migrated["network"]
    assert "local_proxy_url" not in migrated["network"]
    assert "proxy_functions" not in migrated["network"]
    assert "no_proxy_functions" not in migrated["network"]


def test_goal6_unsafe_local_proxy_is_not_promoted_and_emits_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """不完整的旧局部代理配置不得扩大成新的全局 App 代理。"""

    raw = {
        "network": {
            "local_proxy_url": "http://127.0.0.1:7890",
            "proxy_functions": ["login"],
            "no_proxy_functions": [],
        },
    }

    with caplog.at_level(logging.WARNING):
        migrated = migrate_config_dict(raw)

    assert "proxy_url" not in migrated["network"]
    assert any("代理" in record.getMessage() for record in caplog.records)


def test_goal6_legacy_flat_proxy_does_not_widen_without_all_scope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """旧版扁平局部代理也必须经过完整作用域检查。"""

    raw = {
        "LocalProxyUrl": "http://127.0.0.1:7890",
        "NeedProxyFunc": ["login"],
        "NoNeedProxyFunc": [],
    }

    with caplog.at_level(logging.WARNING):
        migrated = migrate_config_dict(raw)

    assert "proxy_url" not in migrated["network"]
    assert any("代理" in record.getMessage() for record in caplog.records)


def test_goal6_conflicting_api_proxy_sources_fail_explicitly() -> None:
    """不同来源给出不同 API 地址时必须显式报告冲突。"""

    with pytest.raises(ValueError):
        migrate_config_dict(
            {
                "DNAUrlProxyUrl": "https://one.example.test",
                "network": {"api_proxy_url": "https://two.example.test"},
            },
        )


def test_goal6_from_config_does_not_mutate_caller_mapping() -> None:
    """model_validate 前后的迁移不能回写 AstrBot 传入的原始字典。"""

    raw = {"display": {"command_prefixes": ["dna"]}}
    original = copy.deepcopy(raw)

    DnabySettings.from_config(raw)

    assert raw == original


def test_goal6_schema_uses_new_groups_and_hides_legacy_fields() -> None:
    """schema 必须与新模型一致，保留业务字段但隐藏重试间隔。"""

    schema = generate_astrbot_schema()

    for group in ("general", "ai", "client_updates"):
        assert group in schema
    assert "agent_tools" not in schema

    client_items = schema["client_updates"]["items"]
    assert client_items["channels"]["type"] == "list"
    assert {"pc_cn", "android_astc_cn"}.issubset(
        set(client_items["channels"]["options"]),
    )
    assert "client_update_enabled" not in schema["notifications"]["items"]
    assert schema["sign_in"]["items"]["scheduled_enabled"] == {
        "type": "bool",
        "description": "旧版每日自动签到任务兼容开关",
        "hint": "仅用于升级旧配置；新配置请使用每个 UID 的自动签到选择",
        "default": True,
        "invisible": True,
    }
    assert "enable_all_users" not in schema["sign_in"]["items"]
    assert (
        schema["notifications"]["items"]["secret_retry_interval_seconds"]["invisible"]
        is True
    )


def test_goal6_unknown_channel_shape_is_rejected() -> None:
    """channels 只接受固定 channel ID 列表，不接受任意标量。"""

    with pytest.raises(ValidationError):
        DnabySettings.from_config(
            {"client_updates": {"channels": "pc_cn"}},
        )
