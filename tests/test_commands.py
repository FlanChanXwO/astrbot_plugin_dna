"""legacy 命令回归与 v0.1 manifest 一致性测试。"""

import os

os.environ.setdefault("DNABY_DATA_DIR", "/tmp/dnaby-test-data")

import json
import re

from src.entry.commands import load_command_registry, manifest_records

COMMANDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "commands.json")


def test_all_commands_nonempty():
    assert len(load_command_registry()) > 0


def test_keys_unique():
    keys = [c.id for c in load_command_registry()]
    assert len(keys) == len(set(keys)), "命令 key 必须唯一"


def test_regexes_compile():
    for cmd in load_command_registry():
        re.compile(cmd.pattern)


def test_handlers_callable():
    for cmd in load_command_registry():
        assert callable(cmd.use_case), f"{cmd.id} use_case 不可调用"


def test_permission_valid():
    for cmd in load_command_registry():
        assert cmd.permission in ("user", "admin", "owner")


def test_examples_match_their_regex():
    for cmd in load_command_registry():
        for eg in cmd.examples:
            assert re.match(cmd.pattern, eg), (
                f"示例「{eg}」不匹配 {cmd.id} 的正则 {cmd.pattern}"
            )


def test_commands_manifest_is_covered_by_code_registry():
    """commands.json 是代码 registry 的生成物，不能脱离实现单独漂移。"""
    with open(COMMANDS_PATH, encoding="utf-8") as file:
        manifest = json.load(file)

    assert manifest == manifest_records(load_command_registry())


def test_specific_delete_command_precedes_generic_uid_delete():
    """重叠正则必须优先命中特定命令，避免别名删除被 UID 命令截获。"""
    registry = load_command_registry()
    message = "删除角色卡米拉别名e2e别名"
    matched = [cmd.id for cmd in registry if re.match(cmd.pattern, message)]

    assert matched[0] == "alias_add_delete"
