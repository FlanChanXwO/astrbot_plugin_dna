"""命令注册表：commands 唯一性 / 正则合法性 / 示例命中测试。

依赖所有 dna_* 模块完成移植（dispatch 聚合 COMMANDS）。
"""

import os

os.environ.setdefault("DNABY_DATA_DIR", "/tmp/dnaby-test-data")

import json
import re

from dnaby.dispatch import ALL_COMMANDS, MASTER_PATTERN

COMMANDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "commands.json")


def test_all_commands_nonempty():
    assert len(ALL_COMMANDS) > 0


def test_keys_unique():
    keys = [c["key"] for c in ALL_COMMANDS]
    assert len(keys) == len(set(keys)), "命令 key 必须唯一"


def test_regexes_compile():
    assert re.compile(MASTER_PATTERN)
    for cmd in ALL_COMMANDS:
        re.compile(cmd["regex"])


def test_handlers_callable():
    for cmd in ALL_COMMANDS:
        assert callable(cmd["handler"]), f"{cmd['key']} handler 不可调用"


def test_permission_valid():
    for cmd in ALL_COMMANDS:
        assert cmd["permission"] in ("user", "admin", "owner")


def test_examples_match_their_regex():
    for cmd in ALL_COMMANDS:
        eg = cmd.get("eg", "")
        if not eg:
            continue
        assert re.match(cmd["regex"], eg), (
            f"示例「{eg}」不匹配 {cmd['key']} 的正则 {cmd['regex']}"
        )


def test_commands_manifest_is_covered_by_dispatch():
    """commands.json 是可审阅的清单，不能声明不存在的分发命令。"""
    with open(COMMANDS_PATH, encoding="utf-8") as file:
        manifest = json.load(file)

    dispatch_by_key = {cmd["key"]: cmd for cmd in ALL_COMMANDS}
    manifest_keys = {cmd["key"] for cmd in manifest}
    assert manifest_keys <= dispatch_by_key.keys()

    for item in manifest:
        cmd = dispatch_by_key[item["key"]]
        for field in ("group", "name", "desc", "eg", "regex", "permission"):
            assert item[field] == cmd[field], f"清单字段不同步: {item['key']}.{field}"
        handler = cmd["handler"]
        assert item["handler"] == f"{handler.__module__}.{handler.__name__}"


def test_specific_delete_command_precedes_generic_uid_delete():
    """重叠正则必须优先命中特定命令，避免别名删除被 UID 命令截获。"""
    message = "删除角色卡米拉别名e2e别名"
    matched = [cmd["key"] for cmd in ALL_COMMANDS if re.match(cmd["regex"], message)]

    assert matched[0] == "alias_add_delete"
