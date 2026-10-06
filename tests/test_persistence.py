"""Task 9 的 SQLAlchemy async 持久化与 Alembic 契约测试。"""

import ast
import asyncio
import sqlite3
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
