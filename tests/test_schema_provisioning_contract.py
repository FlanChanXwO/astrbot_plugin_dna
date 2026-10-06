"""架构契约：生产 schema 只能由 Alembic 建立，且发布包必须携带迁移资产。

这些门禁与 Issue #95 的根因直接对应：如果生产启动路径重新出现
``Base.metadata.create_all()``，或者 release 打包漏掉 ``alembic/``，测试会失败。
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.entry.lifecycle import PluginLifecycle
from src.infrastructure.persistence import Base

ROOT = Path(__file__).resolve().parent.parent
PERSISTENCE_ROOT = ROOT / "src" / "infrastructure" / "persistence"

# 生产源码中唯一允许调用 metadata.create_all 的位置：明确命名的测试 helper。
ALLOWED_CREATE_ALL = {"src/infrastructure/persistence/database.py"}


def _python_sources(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and ".worktrees" not in path.parts
    ]


def _calls_create_all(path: Path) -> list[int]:
    """返回模块中调用 ``*.metadata.create_all(...)`` 的行号。"""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "create_all":
            continue
        target = node.func.value
        if isinstance(target, ast.Attribute) and target.attr == "metadata":
            lines.append(node.lineno)
    return lines


def test_src_never_creates_schema_outside_explicit_test_helper() -> None:
    """``src/`` 中只有 ``create_schema_for_tests`` 可以调用 metadata.create_all。"""

    offenders: list[str] = []
    for path in _python_sources(ROOT / "src"):
        relative = path.relative_to(ROOT).as_posix()
        if relative in ALLOWED_CREATE_ALL:
            continue
        for line in _calls_create_all(path):
            offenders.append(f"{relative}:{line}")

    assert offenders == [], (
        "生产源码不得用 create_all 初始化数据库 schema:\n" + "\n".join(offenders)
    )

    allowed = (ROOT / "src/infrastructure/persistence/database.py").read_text(
        encoding="utf-8"
    )
    assert "def create_schema_for_tests" in allowed
    assert "create_all" in allowed


def test_database_module_keeps_create_all_test_only() -> None:
    """``AsyncDatabase`` 不把 create_all 暴露为生产初始化接口。"""

    source = (PERSISTENCE_ROOT / "database.py").read_text(encoding="utf-8")
    assert "create_schema_for_tests" in source
    assert "DatabaseMigration" not in source


def test_alembic_release_assets_are_present() -> None:
    """release 必须包含 alembic.ini、env.py 和至少一个 revision。"""

    assert (ROOT / "alembic.ini").is_file()
    assert (ROOT / "alembic" / "env.py").is_file()
    versions = sorted((ROOT / "alembic" / "versions").glob("*.py"))
    assert versions, "alembic/versions 不能为空"

    # revision 链必须从 0001 单线连到当前 head，不能出现断裂或双 head。
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic 必须只有一个 head，实际为 {heads}"

    revisions = {revision.revision: revision.down_revision for revision in script.walk_revisions()}
    assert revisions, "alembic revision 链为空"
    base_revisions = [rev for rev, down in revisions.items() if down is None]
    assert base_revisions == ["0001_initial"], base_revisions


def test_alembic_head_matches_declared_models() -> None:
    """当前 head 必须覆盖 ``Base.metadata`` 的全部业务表。"""

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    migration_text = "\n".join(
        (Path(revision.path).read_text(encoding="utf-8"))
        for revision in script.walk_revisions()
    )
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in migration_text, table_name


def test_plugin_lifecycle_rejects_unaligned_hooks() -> None:
    """hook 数量不一致时构造阶段立即失败，而不是回滚时 stop 错对象。"""

    import pytest

    async def _noop() -> None:
        return None

    with pytest.raises(ValueError, match="start_hooks 与 stop_hooks"):
        PluginLifecycle(start_hooks=(_noop,), stop_hooks=())
