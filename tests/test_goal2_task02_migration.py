"""Goal 2 / Task 02：全局身份 schema 与破坏性迁移契约。"""

import asyncio
from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from src.infrastructure.persistence import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    return config


def test_identity_schema_is_global_and_allows_one_active_uid_per_user():
    """身份表不再按 bot_id 隔离，并在数据库层声明 active UID 唯一性。"""

    identity_tables = {
        "account_bindings",
        "credential_records",
        "privacy_settings",
        "group_privacy_settings",
    }

    for table_name in identity_tables:
        table = Base.metadata.tables[table_name]
        assert "bot_id" not in table.c

    account_table = Base.metadata.tables["account_bindings"]
    credential_table = Base.metadata.tables["credential_records"]
    group_privacy_table = Base.metadata.tables["group_privacy_settings"]

    assert {
        tuple(constraint.columns.keys())
        for constraint in account_table.constraints
        if constraint.name == "uq_account_bindings_identity"
    } == {("user_id", "uid")}
    assert {
        tuple(constraint.columns.keys())
        for constraint in credential_table.constraints
        if constraint.name == "uq_credential_records_identity"
    } == {("user_id", "uid")}
    assert {
        tuple(constraint.columns.keys())
        for constraint in group_privacy_table.constraints
        if constraint.name == "uq_group_privacy_settings_identity"
    } == {("group_id",)}

    assert "uq_account_bindings_active_user" in {
        index.name for index in account_table.indexes
    }


@pytest.mark.asyncio
async def test_global_identity_migration_discards_four_tables_and_keeps_sign_records(
    tmp_path: Path,
):
    """从当前旧 head 升级时清空身份/隐私数据，但保留签到历史。"""

    database_path = tmp_path / "migration.sqlite3"
    config = _alembic_config(database_path)
    await asyncio.to_thread(upgrade, config, "0002_privacy_global_identity")

    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, bot_id, group_id, uid, is_active) "
                    "VALUES ('user-1', 'bot-1', 'group-1', '1001', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO credential_records "
                    "(user_id, bot_id, uid, app_cookie) "
                    "VALUES ('user-1', 'bot-1', '1001', 'discard-me')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO privacy_settings "
                    "(user_id, bot_id, group_id, allow_peek, uid_hidden) "
                    "VALUES ('user-1', 'bot-1', NULL, 0, 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO group_privacy_settings "
                    "(group_id, bot_id, force_allow_peek, force_uid_hidden) "
                    "VALUES ('group-1', 'bot-1', 1, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sign_records "
                    "(uid, date, game_sign) VALUES ('1001', '2026-08-28', 1)"
                )
            )
    finally:
        sync_engine.dispose()

    await asyncio.to_thread(upgrade, config, "head")

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_engine.connect() as connection:
            table_columns = await connection.run_sync(
                lambda sync_connection: {
                    table_name: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(table_name)
                    }
                    for table_name in (
                        "account_bindings",
                        "credential_records",
                        "privacy_settings",
                        "group_privacy_settings",
                    )
                }
            )
            counts = await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM account_bindings), "
                    "(SELECT count(*) FROM credential_records), "
                    "(SELECT count(*) FROM privacy_settings), "
                    "(SELECT count(*) FROM group_privacy_settings), "
                    "(SELECT count(*) FROM sign_records)"
                )
            )
            sign_record = await connection.execute(
                text("SELECT uid, game_sign FROM sign_records")
            )

        assert all("bot_id" not in columns for columns in table_columns.values())
        assert counts.one() == (0, 0, 0, 0, 1)
        assert sign_record.one() == ("1001", 1)
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_global_identity_migration_enforces_identity_and_scope_constraints(
    tmp_path: Path,
):
    """升级后的数据库约束覆盖全局身份、active UID 和隐私作用域。"""

    database_path = tmp_path / "constraints.sqlite3"
    config = _alembic_config(database_path)
    await asyncio.to_thread(upgrade, config, "head")

    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, group_id, uid, is_active) "
                    "VALUES ('user-1', 'group-1', '1001', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, group_id, uid, is_active) "
                    "VALUES ('user-1', 'group-2', '1002', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO credential_records "
                    "(user_id, uid, app_cookie) "
                    "VALUES ('user-1', '1001', 'cookie-1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO privacy_settings "
                    "(user_id, group_id, allow_peek, uid_hidden) "
                    "VALUES ('user-1', NULL, 1, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO privacy_settings "
                    "(user_id, group_id, allow_peek, uid_hidden) "
                    "VALUES ('user-1', 'group-1', 0, 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO group_privacy_settings "
                    "(group_id, force_allow_peek, force_uid_hidden) "
                    "VALUES ('group-1', 1, 0)"
                )
            )

        duplicate_cases = (
            (
                "account_bindings",
                "(user_id, group_id, uid, is_active)",
                "('user-1', 'group-3', '1001', 0)",
            ),
            (
                "account_bindings",
                "(user_id, group_id, uid, is_active)",
                "('user-1', 'group-3', '1003', 1)",
            ),
            (
                "credential_records",
                "(user_id, uid, app_cookie)",
                "('user-1', '1001', 'cookie-duplicate')",
            ),
            (
                "privacy_settings",
                "(user_id, group_id, allow_peek, uid_hidden)",
                "('user-1', NULL, 0, 1)",
            ),
            (
                "privacy_settings",
                "(user_id, group_id, allow_peek, uid_hidden)",
                "('user-1', 'group-1', 1, 0)",
            ),
            (
                "group_privacy_settings",
                "(group_id, force_allow_peek, force_uid_hidden)",
                "('group-1', 0, 1)",
            ),
        )
        for table_name, columns, values in duplicate_cases:
            with pytest.raises(IntegrityError), sync_engine.begin() as connection:
                connection.execute(
                    text(
                        f"INSERT INTO {table_name} {columns} "
                        f"VALUES {values}"
                    )
                )
    finally:
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_global_identity_migration_repeated_upgrade_is_a_noop(
    tmp_path: Path,
):
    """同一数据库重复执行 upgrade head 不会再次清空新身份数据。"""

    database_path = tmp_path / "repeat-upgrade.sqlite3"
    config = _alembic_config(database_path)
    await asyncio.to_thread(upgrade, config, "head")

    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, uid, is_active) VALUES ('user-1', '1001', 1)"
                )
            )
        await asyncio.to_thread(upgrade, config, "head")
        with sync_engine.connect() as connection:
            binding = connection.execute(
                text("SELECT user_id, uid, is_active FROM account_bindings")
            ).one()
    finally:
        sync_engine.dispose()

    assert binding == ("user-1", "1001", 1)


@pytest.mark.asyncio
async def test_global_identity_migration_downgrade_restores_empty_legacy_schema(
    tmp_path: Path,
):
    """降级只恢复旧空表结构，签到历史保留且身份数据不被伪造恢复。"""

    database_path = tmp_path / "downgrade.sqlite3"
    config = _alembic_config(database_path)
    await asyncio.to_thread(upgrade, config, "head")

    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_bindings "
                    "(user_id, uid, is_active) VALUES ('user-1', '1001', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO credential_records "
                    "(user_id, uid, app_cookie) "
                    "VALUES ('user-1', '1001', 'discard-me')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sign_records "
                    "(uid, date, game_sign) VALUES ('1001', '2026-08-28', 1)"
                )
            )
        await asyncio.to_thread(downgrade, config, "0002_privacy_global_identity")
        with sync_engine.connect() as connection:
            legacy_columns = {
                table_name: {
                    column["name"]
                    for column in inspect(connection).get_columns(table_name)
                }
                for table_name in (
                    "account_bindings",
                    "credential_records",
                    "privacy_settings",
                    "group_privacy_settings",
                )
            }
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM account_bindings), "
                    "(SELECT count(*) FROM credential_records), "
                    "(SELECT count(*) FROM privacy_settings), "
                    "(SELECT count(*) FROM group_privacy_settings), "
                    "(SELECT count(*) FROM sign_records)"
                )
            ).one()
    finally:
        sync_engine.dispose()

    assert all("bot_id" in columns for columns in legacy_columns.values())
    assert counts == (0, 0, 0, 0, 1)
