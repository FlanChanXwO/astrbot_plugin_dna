"""Task 9 的 SQLAlchemy async 持久化与 Alembic 契约测试。"""

import ast
import asyncio
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import inspect

from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    Base,
    CredentialRecord,
    CredentialRepository,
    DatabaseMigration,
)
from src.infrastructure.persistence.migrations import default_plugin_root


async def _seeded_migration(tmp_path: Path) -> tuple[AsyncDatabase, DatabaseMigration]:
    """为用例准备一个指向隔离 SQLite 的生产 migration runner。"""

    database = AsyncDatabase(tmp_path / "db" / "dna.sqlite3")
    database.path.parent.mkdir(parents=True, exist_ok=True)
    return database, DatabaseMigration(
        database,
        plugin_root=Path(__file__).resolve().parents[1],
    )


def _alembic_revision(database_path: Path) -> str:
    """读取数据库当前 revision，不经过 SQLAlchemy。"""

    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.asyncio
async def test_database_uses_new_async_sqlite_file_and_does_not_touch_legacy_db(
    tmp_path: Path,
):
    """新持久化路径使用独立文件，且不会打开旧 SQLModel 数据库。"""
    legacy_path = tmp_path / "dna.db"
    legacy_bytes = b"legacy-database-fixture"
    legacy_path.write_bytes(legacy_bytes)

    database = AsyncDatabase.from_data_dir(tmp_path)
    try:
        assert database.path == (tmp_path / "db" / "dna.sqlite3").resolve()
        assert database.path.parent.is_dir()
        assert database.url == f"sqlite+aiosqlite:///{database.path}"
        assert database.path != legacy_path.resolve()
        assert legacy_path.read_bytes() == legacy_bytes
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_repository_uses_explicit_transaction_and_rolls_back_on_error(
    tmp_path: Path,
):
    """repository 不隐式创建 session，事务异常时应完整回滚。"""
    database = AsyncDatabase(tmp_path / "dna.sqlite3")
    await database.create_schema_for_tests()
    try:
        async with database.transaction() as session:
            binding = await AccountBindingRepository.add(
                session,
                user_id="user-1",
                uid="1001",
                group_id="group-1",
            )
            assert binding.id is not None

        async with database.session() as session:
            stored = await AccountBindingRepository.get(
                session,
                user_id="user-1",
                uid="1001",
            )
        assert stored is not None
        assert stored.group_id == "group-1"

        with pytest.raises(RuntimeError, match="rollback-fixture"):
            async with database.transaction() as session:
                await AccountBindingRepository.add(
                    session,
                    user_id="user-2",
                    uid="2001",
                )
                raise RuntimeError("rollback-fixture")

        async with database.session() as session:
            rolled_back = await AccountBindingRepository.get(
                session,
                user_id="user-2",
                uid="2001",
            )
        assert rolled_back is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_credential_repository_keeps_secret_fields_out_of_repr_and_snapshot(
    tmp_path: Path,
):
    """凭据可持久化，但 repr 与脱敏快照不得携带 secret 值。"""
    database = AsyncDatabase(tmp_path / "dna.sqlite3")
    await database.create_schema_for_tests()
    app_cookie = "cookie-fixture-value"
    refresh_token = "refresh-fixture-value"
    try:
        async with database.transaction() as session:
            record = await CredentialRepository.add(
                session,
                user_id="user-1",
                uid="1001",
                app_cookie=app_cookie,
                app_refresh_token=refresh_token,
                app_status="有效",
            )
            assert isinstance(record, CredentialRecord)
            assert app_cookie not in repr(record)
            assert refresh_token not in repr(record)
            snapshot = record.redacted_snapshot()
            assert app_cookie not in repr(snapshot)
            assert refresh_token not in repr(snapshot)

        async with database.session() as session:
            stored = await CredentialRepository.get(
                session,
                user_id="user-1",
                uid="1001",
            )
        assert stored is not None
        assert stored.app_cookie == app_cookie
        assert stored.app_refresh_token == refresh_token
    finally:
        await database.dispose()


def test_sqlalchemy_metadata_has_five_new_tables_and_no_sqlmodel_import():
    """新 persistence 包只暴露五张 normalized 表，不依赖旧 SQLModel。"""
    assert set(Base.metadata.tables) == {
        "account_bindings",
        "credential_records",
        "sign_records",
        "privacy_settings",
        "group_privacy_settings",
    }

    persistence_root = Path("src/infrastructure/persistence")
    for source_path in persistence_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert not any(
            (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "sqlmodel" or alias.name.startswith("sqlmodel.")
                    for alias in node.names
                )
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "sqlmodel" or node.module.startswith("sqlmodel."))
            )
            for node in imports
        )


def test_alembic_initial_revision_is_explicit_and_covers_metadata_tables():
    """初始 revision 明确从空库创建新 schema，不承接旧数据库。"""
    migration_path = Path("alembic/versions/0001_initial.py")
    migration_text = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(migration_text)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }

    assert assignments == {"revision": "0001_initial", "down_revision": None}
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        for node in tree.body
    )
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "downgrade"
        for node in tree.body
    )
    for table_name in Base.metadata.tables:
        assert table_name in migration_text


def test_alembic_privacy_identity_revision_is_incremental():
    """隐私唯一性修复使用新 revision，不改写已发布的初始 revision。"""
    migration_path = Path("alembic/versions/0002_privacy_global_identity.py")
    migration_text = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(migration_text)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }

    assert assignments == {
        "revision": "0002_privacy_global_identity",
        "down_revision": "0001_initial",
    }
    assert "uq_privacy_settings_global_identity" in migration_text


def test_alembic_is_declared_without_hardcoded_runtime_database_path():
    """Alembic 配置只声明脚本位置，运行期数据库路径由环境注入。"""
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.lower().startswith("alembic>=") for line in requirements)

    alembic_config = Path("alembic.ini").read_text(encoding="utf-8")
    assert "script_location = %(here)s/alembic" in alembic_config
    assert "sqlalchemy.url =" in alembic_config
    assert "dna.db" not in alembic_config
    assert "dna.sqlite3" not in alembic_config


def test_alembic_prepends_the_plugin_root_not_the_working_directory():
    alembic_config = Path("alembic.ini").read_text(encoding="utf-8")
    prepend_lines = [
        line.strip()
        for line in alembic_config.splitlines()
        if line.strip().startswith("prepend_sys_path")
    ]
    assert prepend_lines == ["prepend_sys_path = %(here)s"], prepend_lines
    assert "prepend_sys_path = ." not in alembic_config


def test_live_command_script_does_not_build_schema_without_migration():
    """对真实数据目录运行的脚本必须走迁移，不能留下未跟踪的 schema。

    ``scripts/test_live_all_commands.py`` 直接作用于 AstrBot 分配的数据目录；如果
    它用 ``create_schema_for_tests`` 建表，就会制造“表存在但没有 ``alembic_version``”
    的库，使后续正常启动无法完成迁移。用 AST 判定实际调用，避免注释文本误判。
    """

    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "test_live_all_commands.py"
    )
    tree = ast.parse(script.read_text(encoding="utf-8"))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "create_schema_for_tests" not in called_attributes
    assert "initialize" in called_attributes


def test_alembic_upgrade_succeeds_from_a_foreign_working_directory(tmp_path: Path):
    """在非插件目录的 CWD 下执行 ``upgrade head`` 必须成功。

    这是 Issue #95 修补在上线时暴露的回归：``alembic/env.py`` 需要 ``import src``，
    而 AstrBot 的工作目录是宿主根（如 ``/AstrBot``）。若 ``prepend_sys_path``
    依赖 CWD，只有从插件目录启动时才会成功，真实部署必然
    ``ModuleNotFoundError``。子进程保证 ``sys.path[0]`` 就是外来 CWD。
    """

    plugin_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "db" / "dna.sqlite3"
    database_path.parent.mkdir(parents=True)
    # 模拟 AstrBot 宿主根：这里没有 src/ 包。
    foreign_cwd = tmp_path / "astrbot-host"
    foreign_cwd.mkdir()
    assert not (foreign_cwd / "src").exists()

    script = textwrap.dedent(
        """
        import asyncio
        import sqlite3
        import sys
        from pathlib import Path

        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        plugin_root = Path(sys.argv[1])
        database_path = Path(sys.argv[2])
        config = Config(str(plugin_root / "alembic.ini"))
        config.set_main_option("script_location", str(plugin_root / "alembic"))
        config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(asyncio.to_thread(command.upgrade, config, "head"))

        head = ScriptDirectory.from_config(config).get_current_head()
        with sqlite3.connect(database_path) as connection:
            revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        tables = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        )
        print(f"HEAD={head}")
        print(f"REVISION={revision}")
        print("TABLES=" + ",".join(tables))
        """,
    )

    result = subprocess.run(
        [sys.executable, "-c", script, str(plugin_root), str(database_path)],
        cwd=foreign_cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "从外来 CWD 执行 alembic upgrade 失败（生产部署形态）:\n"
        + result.stderr[-2000:]
    )
    output = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    assert output["HEAD"] == output["REVISION"]
    assert set(Base.metadata.tables).issubset(set(output["TABLES"].split(",")))


@pytest.mark.asyncio
async def test_alembic_upgrade_and_downgrade_when_dependency_is_available(
    tmp_path: Path,
):
    """依赖已安装时，再用隔离 SQLite 真跑一次 revision 往返。"""
    command = pytest.importorskip("alembic.command")
    config_module = pytest.importorskip("alembic.config")
    Config = config_module.Config
    from sqlalchemy.ext.asyncio import create_async_engine

    database_path = tmp_path / "migration.sqlite3"
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("script_location", str(Path("alembic").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")

    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert set(Base.metadata.tables).issubset(table_names)
    finally:
        await engine.dispose()

    await asyncio.to_thread(command.downgrade, config, "base")


@pytest.mark.asyncio
async def test_fresh_database_migration_creates_every_metadata_table(tmp_path: Path):
    """全新安装不需要任何手动数据库命令即可得到完整 schema。"""

    database, migration = await _seeded_migration(tmp_path)
    try:
        await migration.initialize()

        assert database.path.is_file()
        with sqlite3.connect(database.path) as connection:
            table_names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert set(Base.metadata.tables).issubset(table_names)
        assert _alembic_revision(database.path) == migration.current_head()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_migration_is_idempotent_across_instances(tmp_path: Path):
    """重复调用与插件重载都不会重复破坏数据库或丢失数据。"""

    database, migration = await _seeded_migration(tmp_path)
    try:
        await migration.initialize()
        async with database.transaction() as session:
            await AccountBindingRepository.add(
                session,
                user_id="user-1",
                uid="1001",
                group_id="group-1",
            )

        await migration.initialize()
        reloaded_migration = DatabaseMigration(
            database,
            plugin_root=Path(__file__).resolve().parents[1],
        )
        await reloaded_migration.initialize()

        assert _alembic_revision(database.path) == reloaded_migration.current_head()
        async with database.session() as session:
            stored = await AccountBindingRepository.get(
                session,
                user_id="user-1",
                uid="1001",
            )
        assert stored is not None
        assert stored.group_id == "group-1"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_migration_upgrades_older_revision_and_keeps_data(
    tmp_path: Path,
):
    """已有安装升级插件时保留账号数据，并补齐新 revision 的字段。"""

    command = pytest.importorskip("alembic.command")
    from alembic.config import Config

    database, migration = await _seeded_migration(tmp_path)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    config.set_main_option("sqlalchemy.url", database.url)
    try:
        await asyncio.to_thread(command.upgrade, config, "0004_app_credentials_only")
        assert _alembic_revision(database.path) == "0004_app_credentials_only"
        with sqlite3.connect(database.path) as connection:
            connection.execute(
                "INSERT INTO account_bindings "
                "(user_id, uid, group_id, is_active) VALUES (?, ?, ?, 1)",
                ("user-1", "1001", "group-1"),
            )
            connection.commit()

        await migration.initialize()

        assert _alembic_revision(database.path) == migration.current_head()
        with sqlite3.connect(database.path) as connection:
            rows = connection.execute(
                "SELECT user_id, uid, group_id, auto_sign_enabled "
                "FROM account_bindings"
            ).fetchall()
        assert rows == [("user-1", "1001", "group-1", 1)]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_migration_fails_loudly_without_alembic_assets(tmp_path: Path):
    """发布包缺少 alembic 资产时必须显式失败，而不是回退到 create_all。"""

    database, _ignored = await _seeded_migration(tmp_path)
    bare_root = tmp_path / "plugin-root"
    bare_root.mkdir()
    migration = DatabaseMigration(database, plugin_root=bare_root)
    try:
        with pytest.raises(FileNotFoundError):
            await migration.initialize()
        assert migration.initialized is False
        assert not database.path.exists()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_migration_retries_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """迁移失败后保持未初始化，并允许插件重新加载时重试。"""

    database, migration = await _seeded_migration(tmp_path)
    attempts: list[str] = []
    from alembic import command

    original_upgrade = command.upgrade

    def failing_upgrade(config, revision):
        attempts.append(revision)
        if len(attempts) == 1:
            raise RuntimeError("migration-fixture-failure")
        return original_upgrade(config, revision)

    monkeypatch.setattr(command, "upgrade", failing_upgrade)
    try:
        with pytest.raises(RuntimeError, match="migration-fixture-failure"):
            await migration.initialize()
        assert migration.initialized is False

        await migration.initialize()

        assert migration.initialized is True
        assert attempts == ["head", "head"]
        assert _alembic_revision(database.path) == migration.current_head()
    finally:
        await database.dispose()


async def _make_matching_untracked_database(
    tmp_path: Path,
) -> tuple[AsyncDatabase, Path]:
    """构造场景 C：业务表已经是 head schema，但没有 alembic_version。

    对应用 ``create_schema_for_tests`` 直接写入真实数据目录（例如
    ``scripts/test_live_all_commands.py``）后，再以正常启动路径加载插件的状态。
    """

    command = pytest.importorskip("alembic.command")
    from alembic.config import Config

    database, _migration = await _seeded_migration(tmp_path)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    config.set_main_option("sqlalchemy.url", database.url)
    await asyncio.to_thread(command.upgrade, config, "head")
    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="user-1",
            uid="1001",
            group_id="group-1",
        )
    with sqlite3.connect(database.path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.commit()
    with sqlite3.connect(database.path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "alembic_version" not in tables
    assert set(Base.metadata.tables).issubset(tables)
    return database, database.path


@pytest.mark.asyncio
async def test_matching_untracked_database_is_adopted_at_head(tmp_path: Path):
    """表结构已是当前 head 的未跟踪库被接管为 head，并保留数据。

    这是 Issue #95 退化的边界形态：使用 ``create_schema_for_tests`` 写过真实数据
    目录后，表存在但 ``alembic_version`` 缺失。此时不应因为“表已存在”而让插件
    永远无法启动。
    """

    database, database_path = await _make_matching_untracked_database(tmp_path)
    migration = DatabaseMigration(database, plugin_root=default_plugin_root())
    try:
        await migration.initialize()

        assert _alembic_revision(database_path) == migration.current_head()
        async with database.session() as session:
            stored = await AccountBindingRepository.get(
                session,
                user_id="user-1",
                uid="1001",
            )
        assert stored is not None
        assert stored.group_id == "group-1"

        # 接管后必须幂等：再次运行不会重复建表。
        await migration.initialize()
        assert _alembic_revision(database_path) == migration.current_head()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_matching_untracked_database_with_unrelated_tables_is_adopted(
    tmp_path: Path,
):
    """同一数据库里存在无关表不应阻止接管。

    ``compare_metadata`` 会把 metadata 之外的额外表报为 ``remove_table``；只要
    本插件自己的表结构等于 head，就不应因为邻居表而拒绝启动（其他插件或工具
    可能向同一文件写入额外表）。
    """

    database, database_path = await _make_matching_untracked_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE unrelated_table (id INTEGER PRIMARY KEY)")
        connection.commit()
    migration = DatabaseMigration(database, plugin_root=default_plugin_root())
    try:
        await migration.initialize()

        assert _alembic_revision(database_path) == migration.current_head()
        with sqlite3.connect(database_path) as connection:
            names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "unrelated_table" in names
        async with database.session() as session:
            stored = await AccountBindingRepository.get(
                session,
                user_id="user-1",
                uid="1001",
            )
        assert stored is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_tracked_database_at_head_is_not_re_stamped(tmp_path: Path):
    """已有 ``alembic_version`` 的库不应进入接管分支。"""

    database, migration = await _seeded_migration(tmp_path)
    try:
        await migration.initialize()
        assert _alembic_revision(database.path) == migration.current_head()
        # 接管判定对已跟踪库必须为 False，避免误判与多余 stamp。
        assert await asyncio.to_thread(migration._should_adopt_untracked_schema) is False
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_untracked_database_with_divergent_schema_fails_loudly(
    tmp_path: Path,
):
    """表结构不匹配当前 head 时不得自动接管，而应显式失败。"""

    database, database_path = await _make_matching_untracked_database(tmp_path)
    # 人为制造偏差：删掉一个业务列，使 schema 不再等于 head。
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "ALTER TABLE account_bindings DROP COLUMN auto_sign_enabled"
        )
        connection.commit()
    migration = DatabaseMigration(database, plugin_root=default_plugin_root())
    try:
        with pytest.raises(Exception) as error:
            await migration.initialize()

        assert migration.initialized is False
        assert "alembic_version" not in {
            str(row[0])
            for row in sqlite3.connect(database_path).execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        del error
    finally:
        await database.dispose()
