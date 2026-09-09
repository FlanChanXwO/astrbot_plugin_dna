"""Goal 5 Task 09：用户文档事实、链接和公开边界审计。

测试只覆盖可由仓库内容独立证明的文档契约：相对链接、外链格式、配置 schema
引用、命令清单数量、运行路径和公开文档中的内部残留。历史材料位于
``docs/porting/``/``docs/legacy/``，不在本审计的用户文档范围内。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS_INDEX = ROOT / "docs" / "README.md"
USAGE_DOCS = tuple(sorted((ROOT / "docs" / "usage").glob("*.md")))
PUBLIC_DOCS = (DOCS_INDEX, *USAGE_DOCS)
COMMANDS_DOC = ROOT / "docs" / "usage" / "commands.md"
RESOURCES_DOC = ROOT / "docs" / "usage" / "resources.md"
DEVELOPER_SETUP = ROOT / "docs" / "dev" / "setup.md"
SCHEMA = ROOT / "_conf_schema.json"
COMMANDS = ROOT / "commands.json"

_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_CONFIG_REF_PATTERN = re.compile(
    r"(?<![\w.])"
    r"(?:login|network|sign_in|notifications|display|resources|cache|agent_tools)"
    r"\.[A-Za-z_][\w]*"
)
_PUBLIC_RESIDUE_PATTERN = re.compile(
    r"rsshub|goal[- ]?\d+|task\s*\d+|\bO\d+\b|/Users/|"
    r"\bproduction\b|生产(?:环境|版)|真实账户|fake\s+transport|\bfixture\b|"
    r"\blegacy\b|private\s+(?:checkout|source)|"
    r"(?:cookie|token|password|refresh\s+token|device\s+code|secret)\s*[:=]",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _config_paths() -> set[str]:
    schema = json.loads(_read(SCHEMA))
    return {
        f"{group}.{field}"
        for group, group_schema in schema.items()
        for field in group_schema.get("items", {})
    }


def test_public_document_links_resolve_and_external_links_use_https() -> None:
    missing: list[str] = []
    invalid_external: list[str] = []

    for path in PUBLIC_DOCS:
        text = _read(path)
        for match in _LINK_PATTERN.finditer(text):
            target = match.group(1).strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                if parsed.scheme != "https" or not parsed.netloc:
                    invalid_external.append(f"{path.relative_to(ROOT)}: {target}")
                continue
            if target.startswith("#"):
                continue
            linked_path = (path.parent / unquote(parsed.path)).resolve()
            if not linked_path.is_relative_to(ROOT) or not linked_path.exists():
                missing.append(f"{path.relative_to(ROOT)}: {target}")

    assert not missing, f"用户文档存在失效或越界相对链接：{missing}"
    assert not invalid_external, f"用户文档存在未核实协议的外链：{invalid_external}"


def test_docs_index_exposes_user_path_before_maintainer_archive() -> None:
    text = _read(DOCS_INDEX)
    assert re.search(r"普通用户.*usage/commands\.md", text, re.IGNORECASE | re.DOTALL)
    assert re.search(r"维护者.*历史", text)
    assert text.index("usage/commands.md") < text.index("porting/design.md")


def test_usage_docs_contain_no_internal_migration_or_private_deployment_residue() -> (
    None
):
    residue = {
        str(path.relative_to(ROOT)): _PUBLIC_RESIDUE_PATTERN.findall(_read(path))
        for path in USAGE_DOCS
        if _PUBLIC_RESIDUE_PATTERN.search(_read(path))
    }
    assert not residue, f"用户文档仍有内部迁移、部署或敏感信息残留：{residue}"


def test_resource_manifest_example_includes_runtime_texture_directory() -> None:
    text = _read(RESOURCES_DOC)
    assert '"textures"' in text


def test_usage_docs_only_reference_active_configuration_fields() -> None:
    valid_paths = _config_paths()
    references = {
        reference
        for path in USAGE_DOCS
        for code_span in re.findall(r"`([^`]+)`", _read(path))
        for reference in _CONFIG_REF_PATTERN.findall(code_span)
    }
    unknown = sorted(references - valid_paths)
    assert not unknown, f"用户文档引用了不存在的配置字段：{unknown}"


def test_command_doc_count_matches_manifest() -> None:
    commands = json.loads(_read(COMMANDS))
    assert isinstance(commands, list)
    match = re.search(r"(?<!\d)(\d+)\s*条命令", _read(COMMANDS_DOC))
    assert match is not None, "命令文档必须声明当前 manifest 的命令数量"
    assert int(match.group(1)) == len(commands)


def test_command_doc_lists_every_manifest_name_and_example() -> None:
    commands = json.loads(_read(COMMANDS))
    text = _read(COMMANDS_DOC)
    missing_names = [item["name"] for item in commands if item["name"] not in text]
    missing_examples = [
        example
        for item in commands
        for example in item.get("examples", [])
        if f"`{example}`" not in text
    ]
    assert not missing_names, f"命令文档缺少 manifest 命令：{missing_names}"
    assert not missing_examples, f"命令文档缺少 manifest 示例：{missing_examples}"


def test_developer_setup_uses_portable_paths() -> None:
    text = _read(DEVELOPER_SETUP)
    assert "/Users/" not in text
    assert "当前项目根目录" in text or "ASTRBOT_ROOT" in text
