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

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 参与门禁的工程目录；CHANGELOG.md 属于不可篡改的历史记录，显式排除。
GATE_DIRS = ("src", "tests", "scripts", "pages", "alembic", ".github", "docs")
GATE_FILES = ("main.py", "README.md", "AGENTS.md", "metadata.yaml", "alembic.ini")

# 旧 namespace 的所有大小写变体；word boundary 防止误伤无关英文单词。
_DNABY_PATTERN = re.compile(r"dnaby", re.IGNORECASE)

# 日志 message 开头的人工方括号标签：``[任意内容]`` 后跟空白或直接接文字。
# 只匹配 message 起始位置的标签，不限制标签内的具体词表，因此能覆盖
# 未来新增的任意人工 subsystem 命名；message 正文中的方括号不受影响。
_LOG_PREFIX_PATTERN = re.compile(r"^\s*f?\[[^\]]+\]", re.IGNORECASE)


def _iter_gate_paths() -> list[Path]:
    paths: list[Path] = []
    for name in GATE_DIRS:
        base = ROOT / name
        if base.is_dir():
            paths.extend(p for p in base.rglob("*") if p.is_file())
    for name in GATE_FILES:
        path = ROOT / name
        if path.is_file():
            paths.append(path)
    # 只检查文本类文件；二进制资源（图片/字体）与生成缓存不参与。
    text_suffixes = {
        ".py", ".js", ".html", ".md", ".yml", ".yaml", ".json", ".j2",
        ".ini", ".cfg", ".toml", ".txt", ".sh", ".css",
    }
    skip_parts = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
    gate_self = Path(__file__).resolve()
    return [
        p
        for p in paths
        if p.suffix in text_suffixes
        and not (set(p.parts) & skip_parts)
        # 本文件包含门禁模式定义本身，排除自检。
        and p.resolve() != gate_self
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
        path
        for path in (ROOT / "src").rglob("*.py")
        if "__pycache__" not in path.parts
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


def test_logger_messages_have_no_manual_prefixes() -> None:
    """插件日志 message 不以人工 ``[xxx]`` 方括号标签开头。

    只检查 ``logger.*`` 调用所在行（含跨行调用的首行与 message 字符串行），
    不对普通代码的下标访问（如 ``snapshots[task_id]``）做方括号匹配。
    """

    offenders: list[str] = []
    for path in _python_sources():
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            # 只检查 logger 调用行及其延续的字符串参数行。
            if "logger." not in line:
                stripped = line.strip()
                if not (stripped.startswith('"') or stripped.startswith("f\"")):
                    continue
                # 字符串参数行必须紧跟 logger 调用，避免匹配普通代码。
                previous = lines[lineno - 2].strip() if lineno >= 2 else ""
                if not ("logger." in previous or previous.endswith(",")):
                    continue
            if _LOG_PREFIX_PATTERN.search(line.strip()):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
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
    """matcher 能覆盖已知人工前缀（含 namespace 与 subsystem 变体）。"""

    assert _LOG_PREFIX_PATTERN.search(message), message


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

    assert not _LOG_PREFIX_PATTERN.search(message), message


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
