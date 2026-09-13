"""v0.6.0 breaking namespace contract。

本文件是 namespace 重构的最终门禁（Red Contract）：

- 旧 ``dnaby`` namespace 在当前工程代码中归零（历史记录仅保留在 CHANGELOG.md）；
- Scheduler / Agent Tool / artifact metadata 全部使用 ``dna`` namespace；
- 插件日志 message 不允许以人工 ``[xxx]`` 方括号标签开头。

日志门禁规则：不禁止 message 正文中的 ``[`` ``]``（例如描述性中文标注或
列表下标说明），只禁止 message 以方括号标签开头——插件来源由 AstrBot 平台层
标识，message 应直接以事件描述开头。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 参与门禁的仓库范围：从根目录全量扫描，只保留已知文本扩展名；
# CHANGELOG.md 属于不可篡改的历史记录，gate 测试自身包含 matcher 定义，均显式排除。
GATE_SKIP_DIRS = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    ".worktrees",
)
GATE_EXCLUDE_FILES = ("CHANGELOG.md", "tests/test_namespace_contract.py")
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".html",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".j2",
    ".ini",
    ".cfg",
    ".toml",
    ".txt",
    ".sh",
    ".css",
}

# 旧 namespace 的所有大小写变体；word boundary 防止误伤无关英文单词。
_DNABY_PATTERN = re.compile(r"dnaby", re.IGNORECASE)

# logger message 开头的人工方括号标签判定由 AST 驱动（见 _starts_with_manual_prefix），
# 不再使用行级正则，避免多行调用 / f-string / 引号的边界漏洞。
_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _iter_gate_paths() -> list[Path]:
    """全仓库文本文件扫描范围（root 下所有已知文本扩展名）。"""

    gate_self = Path(__file__).resolve()
    exclude = {ROOT / rel for rel in GATE_EXCLUDE_FILES}
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and p.suffix in TEXT_SUFFIXES
        and not (set(p.parts) & set(GATE_SKIP_DIRS))
        and p.resolve() != gate_self
        and p.resolve() not in exclude
    ]


def test_no_dnaby_namespace_left_in_project() -> None:
    """旧 dnaby namespace 在当前工程中归零（CHANGELOG 历史除外）。"""

    offenders = [
        str(path.relative_to(ROOT))
        for path in _iter_gate_paths()
        if _DNABY_PATTERN.search(path.read_text(encoding="utf-8", errors="strict"))
    ]
    assert offenders == [], "以下文件仍包含旧 dnaby namespace:\n" + "\n".join(offenders)


def _python_sources() -> list[Path]:
    return [
        path for path in (ROOT / "src").rglob("*.py") if "__pycache__" not in path.parts
    ]


def test_python_symbols_use_dna_namespace() -> None:
    """入口符号与命令注册契约使用 dna namespace。"""

    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "class DNAPlugin(Star)" in main_src
    assert "class DnabyPlugin" not in main_src

    commands_src = (ROOT / "src/entry/commands/__init__.py").read_text(encoding="utf-8")
    assert "__dna_command_ids__" in commands_src
    assert "__dnaby_command_ids__" not in commands_src

    settings_src = (ROOT / "src/infrastructure/config/settings.py").read_text(
        encoding="utf-8"
    )
    assert "class DNASettings" in settings_src
    assert "class DnabySettings" not in settings_src


def test_scheduler_task_ids_use_dna_namespace() -> None:
    """内置 scheduler registry 只包含 dna_* 任务 ID。"""

    state_src = (ROOT / "src/infrastructure/scheduler_state.py").read_text(
        encoding="utf-8"
    )
    for task_id in (
        "dna_sign_daily",
        "dna_sign_cleanup",
        "dna_mh_push",
        "dna_ann_poll",
        "dna_client_update_poll",
    ):
        assert f'"{task_id}"' in state_src, f"缺少任务 ID {task_id}"
    assert "dnaby_" not in state_src


def test_agent_tool_names_use_dna_namespace() -> None:
    """Agent Tool 注册名全部为 dna_*。"""

    tools_src = (ROOT / "src/entry/agent_tools/tools.py").read_text(encoding="utf-8")
    assert '"dnaby_' not in tools_src
    # 抽查核心工具名。
    for name in (
        '"dna_player_overview"',
        '"dna_stamina"',
        '"dna_calendar"',
        '"dna_mh"',
    ):
        assert name in tools_src


def test_render_metadata_uses_dna_namespace() -> None:
    """渲染 artifact metadata 使用 dna.text / dna.layout / dna.resources。"""

    for rel in (
        "src/modules/help.py",
        "src/infrastructure/rendering/checkin.py",
        "src/infrastructure/rendering/player.py",
        "src/infrastructure/rendering/notices.py",
        "src/infrastructure/rendering/encyclopedia.py",
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "dnaby." not in src, f"{rel} 仍包含旧 artifact metadata 前缀"


def test_legacy_runtime_layout_support_removed() -> None:
    """pre-v0.5 旧数据布局检测层已删除。"""

    assert not (ROOT / "src/infrastructure/legacy_layout.py").exists()
    assert not (ROOT / "tests/test_legacy_layout.py").exists()
    bootstrap_src = (ROOT / "src/bootstrap.py").read_text(encoding="utf-8")
    assert "LegacyLayoutDetector" not in bootstrap_src


def test_legacy_scheduler_migration_removed() -> None:
    """旧 scheduler 状态/配置迁移兼容层已删除。"""

    state_src = (ROOT / "src/infrastructure/scheduler_state.py").read_text(
        encoding="utf-8"
    )
    assert "migrate_legacy_sign_scheduler" not in state_src
    assert "LEGACY_SIGN_SCHEDULER_MIGRATION" not in state_src

    scheduler_src = (ROOT / "src/infrastructure/scheduler.py").read_text(
        encoding="utf-8"
    )
    assert "_legacy_scheduler_enabled" not in scheduler_src
    assert "migrate_legacy_sign_scheduler" not in scheduler_src

    settings_src = (ROOT / "src/infrastructure/config/settings.py").read_text(
        encoding="utf-8"
    )
    assert "scheduler_enabled_for_runtime" not in settings_src
    assert "_read_legacy_scheduled_enabled" not in settings_src


def _logger_calls(path: Path) -> list[ast.Call]:
    """解析 Python 源码，返回所有 ``logger.<level>(...)`` 调用节点。"""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue
        if node.func.attr not in _LOG_LEVELS:
            continue
        calls.append(node)
    return calls


def _starts_with_manual_prefix(message: ast.expr) -> bool:
    """判断 logger message 的起始静态文本是否以人工 ``[xxx]`` 标签开头。

    覆盖普通字符串（ast.Constant）与 f-string（ast.JoinedStr，检查第一个
    静态片段）；message 正文中的方括号不影响判断。
    """

    if isinstance(message, ast.Constant):
        return isinstance(message.value, str) and message.value.lstrip().startswith("[")
    if isinstance(message, ast.JoinedStr):
        if not message.values:
            return False
        first = message.values[0]
        return (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.lstrip().startswith("[")
        )
    return False


def test_logger_messages_have_no_manual_prefixes() -> None:
    """插件日志 message 不以人工 ``[xxx]`` 方括号标签开头。

    AST 驱动：解析 ``logger.<level>(...)`` 调用的第一个位置参数，
    避免行扫描对多行调用 / f-string / 引号处理的边界漏洞。
    """

    offenders: list[str] = []
    for path in _python_sources():
        for call in _logger_calls(path):
            if call.args and _starts_with_manual_prefix(call.args[0]):
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}")
    assert offenders == [], "以下日志调用仍使用人工前缀:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "message",
    (
        "[dnaby] test",
        "[dna] test",
        "[DNA登录] test",
        "[DNA WebSocket] test",
        "[DNA公告] test",
        "[订阅] test",
        "[resources] test",
        "[client_update] test",
    ),
)
def test_manual_log_prefix_pattern_covers_known_prefixes(message: str) -> None:
    """AST 判定能覆盖已知人工前缀（含 namespace 与 subsystem 变体）。"""

    assert _starts_with_manual_prefix(ast.Constant(value=message)), message
    # f-string 首片段同样命中。
    joined = ast.JoinedStr(
        values=[
            ast.Constant(value=message),
            ast.FormattedValue(value=ast.Name(id="x", ctx=ast.Load())),
        ]
    )
    assert _starts_with_manual_prefix(joined), message


@pytest.mark.parametrize(
    "message",
    (
        # 正文中的合法方括号与列表下标不被误伤。
        "定时任务异常 task_id=dna_sign_daily",
        "丢弃已移除配置 cache.foo（来源 top-level）",
        "公告详情 [置顶] 已解析",
        "查询完成 result=[1, 2, 3]",
        "推送失败 origin=platform:group:g1 [已重试]",
    ),
)
def test_manual_log_prefix_pattern_does_not_match_body_brackets(message: str) -> None:
    """message 正文中的方括号内容不属于人工前缀。"""

    assert not _starts_with_manual_prefix(ast.Constant(value=message)), message


@pytest.mark.parametrize(
    "source",
    (
        'logger.warning("[DNA] test")',
        'logger.warning("[DNA登录] test")',
        'logger.error("[订阅] test")',
        'logger.info(f"[resources] id={value}")',
        'logger.debug(\n    "[client_update] test"\n)',
    ),
)
def test_logger_gate_rejects_manual_prefix_source(source: str, tmp_path: Path) -> None:
    """AST 门禁能从真实源码形态中检出违规调用（单行 / 多行 / f-string）。"""

    source_file = tmp_path / "offender.py"
    source_file.write_text(source, encoding="utf-8")
    calls = _logger_calls(source_file)
    assert calls, source
    assert any(_starts_with_manual_prefix(call.args[0]) for call in calls if call.args)


@pytest.mark.parametrize(
    "source",
    (
        'logger.info("公告详情 [置顶] 已解析")',
        'logger.warning("查询失败 result=[1, 2, 3]")',
        'logger.warning(\n    "推送失败 origin=group [已重试]"\n)',
        'logger.warning(\n    "operation=%s total_seconds=%s",\n    operation,\n    total_seconds,\n)',
        'logger.warning("定时任务异常 task_id=%s", name)',
        'data["key"] = snapshots[task_id]',
    ),
)
def test_logger_gate_accepts_body_brackets(source: str, tmp_path: Path) -> None:
    """message 正文中的方括号与普通下标访问不误报。"""

    source_file = tmp_path / "clean.py"
    source_file.write_text(source, encoding="utf-8")
    calls = _logger_calls(source_file)
    assert not any(
        call.args and _starts_with_manual_prefix(call.args[0]) for call in calls
    )


def test_env_vars_use_dna_namespace() -> None:
    """环境变量契约使用 DNA_*。"""

    for rel in ("alembic/env.py", "tests/conftest.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "DNABY_" not in src, f"{rel} 仍引用旧环境变量"


def test_dashboard_has_no_dnaby_symbols() -> None:
    """Dashboard 不再暴露旧全局标识。"""

    for path in (ROOT / "pages").rglob("*.js"):
        assert "dnaby" not in path.read_text(encoding="utf-8"), str(path)
    for path in (ROOT / "pages").rglob("*.html"):
        assert "dnaby" not in path.read_text(encoding="utf-8"), str(path)
