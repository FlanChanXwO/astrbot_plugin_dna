"""config_manager：schema 生成与 get/set 语义测试。"""

import os

os.environ.setdefault("DNABY_DATA_DIR", "/tmp/dnaby-test-data")

import pytest
from dnaby.dna_config import generate_astrbot_schema
from dnaby.dna_config.dna_config import DNAConfig, DNASignConfig


def test_schema_generation():
    schema = generate_astrbot_schema()
    assert "DNAUID配置" in schema
    assert "DNAUID签到配置" in schema
    default_items = schema["DNAUID配置"]["items"]
    assert default_items["MaxBindNum"]["type"] == "int"
    assert default_items["DNAQRLogin"]["type"] == "bool"
    assert default_items["DNALoginBindHost"]["default"] == "127.0.0.1"
    assert default_items["DNALoginPort"]["default"] == 6189
    assert default_items["MHPushSubscribe"]["type"] == "string"
    assert default_items["MHSubscribe"]["type"] == "list"
    assert default_items["DNAAnnGroups"]["type"] == "object"
    assert default_items["DNAAnnGroups"]["items"] == {}


def test_schema_is_accepted_by_astrbot_config(tmp_path):
    """生成的 schema 必须能被 AstrBotConfig 递归解析。"""
    from astrbot.core import AstrBotConfig

    config = AstrBotConfig(
        config_path=str(tmp_path / "config.json"),
        schema=generate_astrbot_schema(),
    )
    assert config["DNAUID配置"]["DNAAnnGroups"] == {}


def test_get_config_defaults():
    # 未绑定 AstrBotConfig 时回退 schema 默认
    assert DNAConfig.get_config("MaxBindNum").data == 2
    assert DNAConfig.get_config("DNAQRLogin").data is False
    assert DNASignConfig.get_config("DNASignin").data is False
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
