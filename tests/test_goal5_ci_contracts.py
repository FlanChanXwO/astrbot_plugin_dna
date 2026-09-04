"""Goal 5 Task 03：CI、发布脚本与用户文档的 TDD Red 契约。

本文件只测试已在 ``goal-5/plan.md`` 中确认的公共 seam：

- loader 脚本的正式版本选择、插件 staging 和 CLI 失败报告；
- Changelog 解析器的首个版本段和显式失败；
- PR workflow 的触发器、权限、Python 版本和最新 stable 选择；
- README 的用户向章节、相对链接和公开内容边界。

当前 task 只建立 Red 测试，不实现目标脚本或 workflow。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_SCRIPT = ROOT / "scripts" / "ci" / "check_astrbot_plugin_load.py"
RELEASE_NOTES_SCRIPT = ROOT / "scripts" / "ci" / "release_notes.py"
PLUGIN_LIFECYCLE_WORKFLOW = ROOT / ".github" / "workflows" / "plugin-lifecycle.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-from-changelog.yml"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
METADATA = ROOT / "metadata.yaml"
FIXTURE_ASTRBOT_VERSION = "fixture-runtime"


def _load_module(path: Path, module_name: str) -> ModuleType:
    """从目标公共脚本加载模块；目标不存在时让 Red 失败保持可定位。"""

    assert path.is_file(), f"目标脚本不存在：{path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None, f"无法加载目标脚本：{path}"
    module = importlib.util.module_from_spec(spec)
    # 注册模块后再执行，保证目标脚本声明 dataclass 等类型时具备标准 import 语义。
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _read_required_file(path: Path) -> str:
    assert path.is_file(), f"目标文件不存在：{path}"
    return path.read_text(encoding="utf-8")


def _relative_markdown_links(text: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or target.startswith("#"):
            continue
        links.append(unquote(parsed.path))
    return links


def test_latest_stable_version_ignores_prereleases_and_selects_highest_tag() -> None:
    module = _load_module(CI_SCRIPT, "goal5_loader_contracts")

    assert module.select_latest_stable_version(
        [
            "v4.27.9",
            "v4.27.10",
            "v4.28.0-beta.1",
            "v4.29.0-alpha.2",
            "v4.30.0-rc.1",
            "not-a-version",
        ],
    ) == "v4.27.10"


def test_latest_stable_version_fails_when_no_formal_release_exists() -> None:
    module = _load_module(CI_SCRIPT, "goal5_loader_no_stable_contracts")

    with pytest.raises(ValueError, match="stable|formal|version"):
        module.select_latest_stable_version(
            ["v4.28.0-beta.1", "v4.29.0-rc.1", "master"],
        )


def test_stage_plugin_copies_source_but_excludes_runtime_and_repository_data(
    tmp_path: Path,
) -> None:
    module = _load_module(CI_SCRIPT, "goal5_staging_contracts")
    plugin_dir = tmp_path / "plugin"
    astrbot_root = tmp_path / "astrbot-root"

    (plugin_dir / ".git").mkdir(parents=True)
    (plugin_dir / ".git" / "config").write_text("credential=must-not-copy", encoding="utf-8")
    (plugin_dir / "data").mkdir()
    (plugin_dir / "data" / "dnaby.sqlite3").write_bytes(b"runtime database")
    (plugin_dir / "__pycache__").mkdir()
    (plugin_dir / "__pycache__" / "main.pyc").write_bytes(b"bytecode")
    (plugin_dir / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (plugin_dir / "cookies.json").write_text("{\"cookie\": \"secret\"}", encoding="utf-8")
    (plugin_dir / "main.py").write_text("PLUGIN_SENTINEL = True\n", encoding="utf-8")
    (plugin_dir / "metadata.yaml").write_text("name: astrbot_plugin_dnaby\n", encoding="utf-8")

    staged = module.stage_plugin(
        plugin_dir=plugin_dir,
        astrbot_root=astrbot_root,
        plugin_name="astrbot_plugin_dnaby",
    )

    assert staged == astrbot_root / "data" / "plugins" / "astrbot_plugin_dnaby"
    assert (staged / "main.py").read_text(encoding="utf-8") == "PLUGIN_SENTINEL = True\n"
    assert (staged / "metadata.yaml").is_file()
    assert not (staged / ".git").exists()
    assert not (staged / "data").exists()
    assert not (staged / "__pycache__").exists()
    assert not (staged / ".env").exists()
    assert not (staged / "cookies.json").exists()


def test_loader_cli_exposes_required_arguments() -> None:
    _read_required_file(CI_SCRIPT)

    result = subprocess.run(
        [sys.executable, str(CI_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    help_text = f"{result.stdout}\n{result.stderr}"
    for option in (
        "--astrbot-source",
        "--astrbot-version",
        "--plugin-dir",
        "--astrbot-root",
        "--plugin-name",
    ):
        assert option in help_text


def test_loader_failure_reports_phase_traceback_identity_and_cleans_root(
    tmp_path: Path,
) -> None:
    _read_required_file(CI_SCRIPT)
    plugin_dir = tmp_path / "plugin"
    astrbot_source = tmp_path / "astrbot-source"
    astrbot_root = tmp_path / "astrbot-root"
    astrbot_source.mkdir()
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text("PLUGIN_SENTINEL = True\n", encoding="utf-8")
    (plugin_dir / "metadata.yaml").write_text(
        "name: astrbot_plugin_dnaby\nversion: v0.2.0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(CI_SCRIPT),
            "--astrbot-source",
            str(astrbot_source),
            "--astrbot-version",
            FIXTURE_ASTRBOT_VERSION,
            "--plugin-dir",
            str(plugin_dir),
            "--astrbot-root",
            str(astrbot_root),
            "--plugin-name",
            "astrbot_plugin_dnaby",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert re.search(r"phase\s*[:=]", output, re.IGNORECASE)
    assert "Traceback (most recent call last)" in output
    assert FIXTURE_ASTRBOT_VERSION in output
    assert "astrbot_plugin_dnaby" in output
    assert re.search(r"commit", output, re.IGNORECASE)
    assert not astrbot_root.exists()


def test_changelog_parser_returns_only_requested_release_and_rejects_invalid_input() -> None:
    module = _load_module(RELEASE_NOTES_SCRIPT, "goal5_release_notes_contracts")
    changelog = """# 更新日志

## [v0.2.0] - 2026-09-02

### Added

- First public release.

## [v0.1.0] - 2026-08-01

- Older release.
"""

    notes = module.parse_changelog(changelog, version="v0.2.0")
    assert notes.version == "v0.2.0"
    assert notes.date == "2026-09-02"
    assert "First public release." in notes.body
    assert "Older release." not in notes.body

    invalid_inputs = (
        "# 更新日志\n",
        "# 更新日志\n\n## [v0.2.0] - 2026-09-02\n",
        "# 更新日志\n\n## [v0.1.0] - 2026-08-01\n\n- wrong version\n",
        (
            "# 更新日志\n\n## [v0.2.0] - 2026-09-02\n\n- first\n"
            "\n## [v0.2.0] - 2026-09-03\n\n- duplicate\n"
        ),
    )
    for invalid in invalid_inputs:
        with pytest.raises(ValueError):
            module.parse_changelog(invalid, version="v0.2.0")


def test_plugin_lifecycle_workflow_is_pr_only_read_only_and_uses_latest_stable() -> None:
    text = _read_required_file(PLUGIN_LIFECYCLE_WORKFLOW)
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)

    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    assert set(trigger) == {"pull_request"}
    assert "pull_request_target" not in text

    assert workflow.get("permissions") == {"contents": "read"}
    for job in workflow.get("jobs", {}).values():
        if "permissions" in job:
            assert job["permissions"] == {"contents": "read"}

    assert "3.12" in text
    assert "git ls-remote --tags --refs" in text
    assert "select_latest_stable_version" in text
    assert "scripts/ci/check_astrbot_plugin_lifecycle.py" in text
    assert "matrix.source" not in text
    assert not re.search(r"(?m)^\s*-\s+master\s*$", text)
    assert "continue-on-error" not in text
    assert "secrets." not in text


def test_plugin_lifecycle_checkout_does_not_persist_github_credentials() -> None:
    workflow = yaml.safe_load(_read_required_file(PLUGIN_LIFECYCLE_WORKFLOW))
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs", {})
    checkout_steps = [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkout_steps) == 1
    assert checkout_steps[0].get("with", {}).get("persist-credentials") is False


def test_release_tag_rejects_option_and_path_injection_prefixes() -> None:
    module = _load_module(RELEASE_NOTES_SCRIPT, "goal5_release_tag_security_contracts")

    assert module.release_tag("v0.2.0", tag_prefix="release-") == "release-0.2.0"
    for prefix in (
        "-draft-",
        "../",
        "refs/tags/",
        "release?check=1",
        "release#fragment",
    ):
        with pytest.raises(ValueError):
            module.release_tag("v0.2.0", tag_prefix=prefix)


def test_loader_does_not_use_bare_or_baseexception_handlers() -> None:
    tree = ast.parse(_read_required_file(CI_SCRIPT), filename=str(CI_SCRIPT))
    broad_handlers = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and (
            node.type is None
            or (isinstance(node.type, ast.Name) and node.type.id == "BaseException")
        )
    ]
    assert broad_handlers == []


def test_workflow_actions_are_pinned_to_immutable_commits() -> None:
    action_refs: list[tuple[Path, str]] = []
    for workflow_path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for reference in re.findall(
            r"^\s*uses:\s*([^\s#]+)",
            _read_required_file(workflow_path),
            flags=re.MULTILINE,
        ):
            action_refs.append((workflow_path, reference))

    assert action_refs
    for workflow_path, reference in action_refs:
        assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", reference), (
            workflow_path,
            reference,
        )


def test_readme_has_user_installation_configuration_and_support_sections() -> None:
    text = _read_required_file(README)
    required_heading_patterns = (
        r"^##+\s+.*功能",
        r"^##+\s+.*支持.*版本",
        r"^##+\s+.*手动安装",
        r"^##+\s+.*配置",
        r"^##+\s+.*命令",
        r"^##+\s+.*数据目录.*隐私",
        r"^##+\s+.*常见问题",
        r"^##+\s+.*开发.*本地测试",
        r"^##+\s+.*问题反馈.*贡献",
        r"^##+\s+License\s*$",
    )
    for pattern in required_heading_patterns:
        assert re.search(pattern, text, re.MULTILINE | re.IGNORECASE), pattern


def test_readme_relative_links_resolve_inside_repository() -> None:
    text = _read_required_file(README)

    missing: list[str] = []
    for target in _relative_markdown_links(text):
        path = (README.parent / target).resolve()
        if not path.is_file() and not path.is_dir():
            missing.append(target)
    assert not missing, f"README 存在失效相对链接：{missing}"


def test_public_ci_release_docs_have_no_rsshub_or_internal_private_residue() -> None:
    paths = (README, CHANGELOG, PLUGIN_LIFECYCLE_WORKFLOW, RELEASE_WORKFLOW)
    contents = {path: _read_required_file(path) for path in paths}
    forbidden = re.compile(
        r"rsshub|goal[- ]?\d+|task\s*\d+|\bO\d+\b|"
        r"/Users/|private checkout|production|真实账号|私有源码|detached|"
        r"(?:cookie|token|password|secret)\s*[:=]",
        re.IGNORECASE,
    )

    residue = {
        str(path.relative_to(ROOT)): forbidden.findall(text)
        for path, text in contents.items()
        if forbidden.search(text)
    }
    assert not residue, f"公开治理/发布/用户文档仍有内部或敏感残留：{residue}"


def test_changelog_version_matches_metadata_and_does_not_publish_porting_history() -> None:
    changelog = _read_required_file(CHANGELOG)
    metadata = yaml.safe_load(_read_required_file(METADATA))
    assert isinstance(metadata, dict)

    match = re.search(
        r"(?m)^##\s+\[(v\d+\.\d+\.\d+)\]\s+-\s+(\d{4}-\d{2}-\d{2})\s*$",
        changelog,
    )
    assert match is not None, "根 CHANGELOG 首个版本 heading 必须使用固定格式"
    assert match.group(1) == metadata["version"]
    assert match.group(2) == "2026-09-02"
    assert not re.search(r"(?im)^##+\s+(?:Goal|Task)\b", changelog)
    assert "docs/porting/" not in changelog
