"""config_manager：schema 生成与 get/set 语义测试。"""

import os

os.environ.setdefault("DNABY_DATA_DIR", "/tmp/dnaby-test-data")

import pytest

from src.infrastructure.config import generate_legacy_schema as generate_astrbot_schema
from src.infrastructure.config.schema import (
    generate_astrbot_schema as generate_typed_schema,
)
from src.infrastructure.config.settings import (
    DnabySettings,
    DNAConfig,
    DNASignConfig,
    SignInSettings,
)


def test_schema_generation():
    schema = generate_astrbot_schema()
    assert "DNAUID配置" in schema
    assert "DNAUID签到配置" in schema
    default_items = schema["DNAUID配置"]["items"]
    assert default_items["MaxBindNum"]["type"] == "int"
    assert default_items["DNAQRLogin"]["type"] == "bool"
    assert default_items["DNALoginBindHost"]["default"] == "127.0.0.1"
    assert default_items["DNALoginPort"]["default"] == 6189
    assert "MHPushSubscribe" not in default_items
    assert "MHCache" not in default_items
    assert default_items["MHSubscribe"]["type"] == "list"
    assert "DNAAnnGroups" not in default_items
    assert "DNASignin" not in schema["DNAUID签到配置"]["items"]


def test_typed_sign_in_config_has_no_feature_enable_switches():
    """签到功能固定启用，公开配置不再暴露游戏或社区开启项。"""

    schema = generate_typed_schema()
    sign_items = schema["sign_in"]["items"]
    assert "game_enabled" not in sign_items
    assert "community_enabled" not in sign_items
    assert "game_enabled" not in SignInSettings.model_fields
    assert "community_enabled" not in SignInSettings.model_fields


def test_deprecated_sign_enable_switches_are_ignored_on_upgrade():
    """旧配置残留的关闭值不得阻止插件启动或重新关闭签到功能。"""

    settings = DnabySettings.from_config(
        {"sign_in": {"game_enabled": False, "community_enabled": False}},
    )
    assert settings.sign_in == SignInSettings()


def test_schema_is_accepted_by_astrbot_config(tmp_path):
    """生成的 schema 必须能被 AstrBotConfig 递归解析。"""
    from astrbot.core import AstrBotConfig

    config = AstrBotConfig(
        config_path=str(tmp_path / "config.json"),
        schema=generate_astrbot_schema(),
    )
    assert "DNAAnnGroups" not in config["DNAUID配置"]


def test_get_config_defaults():
    # 未绑定 AstrBotConfig 时回退 schema 默认
    assert DNAConfig.get_config("MaxBindNum").data == 2
    assert DNAConfig.get_config("DNAQRLogin").data is False
    assert DNASignConfig.get_config("DNABBSLink").data == [
        "bbs_sign",
        "bbs_detail",
        "bbs_like",
        "bbs_share",
        "bbs_reply",
    ]


def test_bind_and_get():
    store = {}
    store.setdefault("DNAUID配置", {})["MaxBindNum"] = 5
    DNAConfig.bind(store)
    assert DNAConfig.get_config("MaxBindNum").data == 5


def test_get_config_unknown_key_raises():
    with pytest.raises(KeyError):
        DNAConfig.get_config("不存在的键")


def test_display_settings_supports_configurable_command_prefix():
    settings = DnabySettings.from_config({"display": {"command_prefix": "dna"}})
    assert settings.display.command_prefix == "dna"
    assert settings.display.command_prefixes == ["dna"]

    multi_settings = DnabySettings.from_config(
        {"display": {"command_prefixes": ["kk", "dna"]}}
    )
    assert multi_settings.display.command_prefixes == ["kk", "dna"]
    assert multi_settings.display.command_prefix == "kk"

    default_settings = DnabySettings.from_config({})
    assert default_settings.display.command_prefix == "dna"
    assert default_settings.display.command_prefixes == ["dna"]


def test_display_settings_rejects_invalid_prefix_values():
    from pydantic import ValidationError

    from src.infrastructure.config.settings import DisplaySettings

    for value in (None, 123, {"prefix": "kk"}):
        with pytest.raises(ValidationError):
            DisplaySettings(command_prefixes=value)

    with pytest.raises(ValidationError):
        DnabySettings.from_config({"display": {"command_prefix": {"prefix": "kk"}}})


def test_sign_time_string_format_and_rejects_invalid_values():
    from pydantic import ValidationError

    # 正常 HH:mm 格式
    assert SignInSettings(sign_time="08:30").sign_time == "08:30"
    assert SignInSettings(sign_time="00:05").sign_time == "00:05"
    assert SignInSettings(sign_time="23:59").sign_time == "23:59"
    # 单数字小时归一化
    assert SignInSettings(sign_time="8:30").sign_time == "08:30"
    # 兼容 list/tuple 输入并归一化为 HH:mm 字符串
    assert SignInSettings(sign_time=[1, 30]).sign_time == "01:30"

    for value in ("24:00", "12:60", "invalid", "", None, [25, 0]):
        with pytest.raises(ValidationError):
            SignInSettings(sign_time=value)


def test_all_config_items_resolve_from_typed_config():
    """测试 typed 配置字典能够完整生效，包括 legacy namespace 和 typed settings。"""
    config_dict = {
        "login": {
            "url": "http://127.0.0.1:8000",
            "bind_host": "0.0.0.0",
            "port": 9000,
            "transport": "http_poll",
            "shared_secret": "my-secret",
            "tencent_docs": True,
            "qr_login": True,
            "forward_login": True,
            "max_bind_count": 5,
        },
        "network": {
            "api_base_url": "http://proxy.api",
            "proxy_url": "http://127.0.0.1:7890",
            "websocket_continue_seconds": 600,
            "websocket_wait_seconds": 10,
        },
        "sign_in": {
            "community_tasks": ["bbs_sign"],
            "default_auto_sign_enabled": True,
            "sign_time": "06:30",
            "concurrency": 3,
            "concurrency_interval_seconds": [5, 10],
            "private_report": True,
            "group_report": True,
            "group_report_image": True,
        },
        "notifications": {
            "announcement_enabled": False,
            "announcement_check_minutes": 15,
            "secret_simple_image": True,
        },
        "general": {
            "command_prefixes": ["dna"],
            "allow_mention_query": False,
        },
        "display": {
            "guide_providers": ["猫冬"],
            "show_unowned_roles": False,
        },
    }
    settings = DnabySettings.from_config(config_dict)

    # 验证 typed settings
    assert settings.login.url == "http://127.0.0.1:8000"
    assert settings.login.bind_host == "0.0.0.0"
    assert settings.login.port == 9000
    assert settings.login.transport == "http_poll"
    assert settings.login.shared_secret.get_secret_value() == "my-secret"
    assert settings.login.tencent_docs is True
    assert settings.login.qr_login is True
    assert settings.login.forward_login is True
    assert settings.login.max_bind_count == 5

    assert settings.network.api_base_url == "http://proxy.api"
    assert settings.network.proxy_url == "http://127.0.0.1:7890"
    assert settings.network.websocket_continue_seconds == 600
    assert settings.network.websocket_wait_seconds == 10

    assert settings.sign_in.community_tasks == ["bbs_sign"]
    assert settings.sign_in.default_auto_sign_enabled is True
    assert settings.sign_in.sign_time == "06:30"
    assert settings.sign_in.concurrency == 3
    assert settings.sign_in.concurrency_interval_seconds == (5, 10)
    assert settings.sign_in.private_report is True
    assert settings.sign_in.group_report is True
    assert settings.sign_in.group_report_image is True

    assert settings.notifications.announcement_enabled is False
    assert settings.notifications.announcement_check_minutes == 15
    assert settings.notifications.secret_simple_image is True

    assert settings.general.command_prefixes == ["dna"]
    assert settings.general.allow_mention_query is False
    assert settings.display.guide_providers == ["猫冬"]
    assert settings.display.show_unowned_roles is False

    # 验证 legacy namespace get_config 同步生效
    assert DNAConfig.get_config("MaxBindNum").data == 5
    assert DNAConfig.get_config("DNALoginUrl").data == "http://127.0.0.1:8000"
    assert DNAConfig.get_config("DNALoginBindHost").data == "0.0.0.0"
    assert DNAConfig.get_config("DNALoginPort").data == 9000
    assert DNAConfig.get_config("DNALoginTransport").data == "http_poll"
    assert DNAConfig.get_config("DNALoginSecret").data == "my-secret"
    assert DNAConfig.get_config("DNAQRLogin").data is True
    assert DNAConfig.get_config("DNALoginForward").data is True
    assert DNAConfig.get_config("DNATencentWord").data is True
    assert DNAConfig.get_config("CommandPrefix").data == "dna"
    assert DNAConfig.get_config("DNAPaint").data == ["猫冬"]
    assert DNAConfig.get_config("DNAPaintShowNone").data is False
    assert DNAConfig.get_config("DNAAt").data is False
    assert DNAConfig.get_config("AllowAtQuery").data is False
    assert DNAConfig.get_config("DNAAnnState").data is False
    assert DNAConfig.get_config("DNAUrlProxyUrl").data == "http://proxy.api"
    assert DNAConfig.get_config("LocalProxyUrl").data == "http://127.0.0.1:7890"
    assert DNAConfig.get_config("NeedProxyFunc").data == []
    assert DNAConfig.get_config("NoNeedProxyFunc").data == []
    assert DNAConfig.get_config("WebSocketContinueTime").data == 600
    assert DNAConfig.get_config("WebSocketWaitTime").data == 10

    assert DNASignConfig.get_config("SignTime").data == "06:30"
    assert DNASignConfig.get_config("SignAllUser").data is True
    assert DNASignConfig.get_config("DNABBSLink").data == ["bbs_sign"]
    assert list(DNASignConfig.get_config("SignRandomTime").data) == [5, 10]
    assert DNASignConfig.get_config("PrivateSignReport").data is True
    assert DNASignConfig.get_config("GroupSignReport").data is True
    assert DNASignConfig.get_config("GroupSignReportPic").data is True


def test_build_runtime_propagates_all_settings(tmp_path):
    """测试 build_runtime 将全部 typed 配置项正确下发到对应 service / scheduler / renderer。"""
    from types import SimpleNamespace

    from src.bootstrap import build_runtime
    from src.infrastructure.persistence import AsyncDatabase

    config_dict = {
        "login": {
            "max_bind_count": 7,
        },
        "general": {
            "command_prefixes": ["dna"],
            "allow_mention_query": False,
        },
        "display": {
            "guide_providers": ["猫冬"],
            "show_unowned_roles": False,
        },
        "sign_in": {
            "community_tasks": ["bbs_sign"],
            "default_auto_sign_enabled": True,
            "sign_time": "07:15",
            "concurrency": 4,
            "concurrency_interval_seconds": [2, 6],
            "group_report": True,
            "group_report_image": True,
        },
        "notifications": {
            "announcement_enabled": False,
            "announcement_check_minutes": 20,
            "secret_simple_image": True,
            "secret_push_minute": 17,
            "secret_retry_interval_seconds": 2,
        },
    }
    db = AsyncDatabase(tmp_path / "test.sqlite3")
    context = SimpleNamespace(register_web_api=lambda *args: None)
    runtime = build_runtime(context, config_dict, database=db)

    # 1. 验证 settings 字段
    assert runtime.settings.login.max_bind_count == 7
    assert runtime.settings.general.command_prefixes == ["dna"]
    assert runtime.settings.general.allow_mention_query is False
    assert runtime.settings.display.guide_providers == ["猫冬"]
    assert runtime.settings.display.show_unowned_roles is False
    assert runtime.settings.sign_in.sign_time == "07:15"
    assert runtime.settings.sign_in.default_auto_sign_enabled is True
    assert runtime.settings.sign_in.concurrency == 4
    assert runtime.settings.sign_in.concurrency_interval_seconds == (2, 6)
    assert runtime.settings.notifications.announcement_enabled is False
    assert runtime.settings.notifications.announcement_check_minutes == 20
    assert runtime.settings.notifications.secret_simple_image is True
    assert runtime.settings.notifications.secret_push_minute == 17
    assert runtime.settings.notifications.secret_retry_interval_seconds == 2

    # 2. 验证下发到各个具体 service / scheduler
    account_service = runtime.services["account_service"]
    assert account_service.max_bind_count == 7
    assert account_service.default_auto_sign_enabled is True

    privacy_service = runtime.services["privacy_service"]
    assert privacy_service.allow_mention_query is False

    player_service = runtime.services["player_service"]
    assert player_service.show_unowned_roles is False

    encyclopedia_service = runtime.services["encyclopedia_service"]
    assert encyclopedia_service.guide_providers == ("猫冬",)

    checkin_service = runtime.services["checkin_service"]
    assert checkin_service.community_tasks == ("bbs_sign",)
    assert checkin_service.concurrency == 4
    assert checkin_service.interval_range == (2, 6)
    assert checkin_service.group_report is True
    assert checkin_service.group_report_image is True

    sign_scheduler = runtime.services["sign_scheduler"]
    assert sign_scheduler.sign_time == (7, 15)

    notices_scheduler = runtime.services["notices_scheduler"]
    assert notices_scheduler.announcement_enabled is False
    assert notices_scheduler.push_time == (17, 0)
    assert notices_scheduler.poll_minutes == 20

    # 3. 验证命令前缀动态生效
    help_spec = runtime.commands.get("help")
    assert help_spec.pattern.startswith("^dna")


def test_schema_descriptions_have_no_periods_and_hints_are_populated():
    """配置项显示名称不能有句号，提示信息必须放到 hint。"""
    import json
    from pathlib import Path

    from src.infrastructure.config.schema import generate_astrbot_schema

    schema = generate_astrbot_schema()
    for group_name, group in schema.items():
        assert "。" not in group["description"], (
            f"分组 {group_name} description 包含句号"
        )
        assert not group["description"].endswith("."), (
            f"分组 {group_name} description 包含英文句号结尾"
        )
        for field_name, field_def in group.get("items", {}).items():
            desc = field_def.get("description", "")
            assert "。" not in desc, (
                f"字段 {group_name}.{field_name} description 包含句号: {desc}"
            )
            assert not desc.endswith("."), (
                f"字段 {group_name}.{field_name} description 包含英文句号结尾: {desc}"
            )
            hint = field_def.get("hint", "")
            assert hint, f"字段 {group_name}.{field_name} 缺少 hint"

    # 同时校验根目录 _conf_schema.json
    schema_file = Path(__file__).parents[1] / "_conf_schema.json"
    if schema_file.exists():
        disk_schema = json.loads(schema_file.read_text(encoding="utf-8"))
        for group_name, group in disk_schema.items():
            assert "。" not in group["description"]
            for field_name, field_def in group.get("items", {}).items():
                desc = field_def.get("description", "")
                assert "。" not in desc, (
                    f"_conf_schema.json 字段 {group_name}.{field_name} description 包含句号: {desc}"
                )
                assert field_def.get("hint"), (
                    f"_conf_schema.json 字段 {group_name}.{field_name} 缺少 hint"
                )


def test_numeric_config_fields_use_int_types():
    """纯数字配置项应使用 int / float 类型。"""
    from src.infrastructure.config.schema import generate_astrbot_schema

    schema = generate_astrbot_schema()
    assert schema["login"]["items"]["port"]["type"] == "int"
    assert schema["login"]["items"]["max_bind_count"]["type"] == "int"
    assert schema["network"]["items"]["websocket_continue_seconds"]["type"] == "int"
    assert schema["network"]["items"]["websocket_wait_seconds"]["type"] == "int"
    assert schema["sign_in"]["items"]["concurrency"]["type"] == "int"
    assert (
        schema["notifications"]["items"]["announcement_check_minutes"]["type"] == "int"
    )


def test_legacy_nested_and_flat_config_migration():
    """手动/自动迁移：从 GsCore 旧版嵌套结构和扁平结构迁移到 typed 配置。"""
    from src.infrastructure.config.settings import DnabySettings, migrate_config_dict

    legacy_gscore = {
        "DNAUID配置": {
            "MaxBindNum": 4,
            "DNALoginUrl": "http://login.local:8080",
            "CommandPrefix": "dna",
            "DNAAnnGroups": {"group_100": True},
            "MHSimplePic": True,
        },
        "DNAUID签到配置": {
            "SignTime": "08:00",
            "SignAllUser": True,
            "PrivateSignReport": True,
        },
    }
    migrated = migrate_config_dict(legacy_gscore)
    assert migrated["login"]["max_bind_count"] == 4
    assert migrated["login"]["url"] == "http://login.local:8080"
    assert migrated["general"]["command_prefixes"] == ["dna"]
    assert migrated["notifications"]["secret_simple_image"] is True
    assert migrated["sign_in"]["sign_time"] == "08:00"
    assert migrated["sign_in"]["default_auto_sign_enabled"] is True
    assert migrated["sign_in"]["private_report"] is True

    settings = DnabySettings.from_config(legacy_gscore)
    assert settings.login.max_bind_count == 4
    assert settings.login.url == "http://login.local:8080"
    assert settings.display.command_prefix == "dna"
    assert settings.notifications.secret_simple_image is True
    assert settings.sign_in.sign_time == "08:00"
    assert settings.sign_in.default_auto_sign_enabled is True


def test_config_migration_rejects_malformed_known_sections():
    from src.infrastructure.config.settings import migrate_config_dict

    with pytest.raises(TypeError, match="sign_in"):
        migrate_config_dict({"sign_in": "not-an-object"})

    with pytest.raises(TypeError, match="DNAUID签到配置"):
        migrate_config_dict({"DNAUID签到配置": []})
