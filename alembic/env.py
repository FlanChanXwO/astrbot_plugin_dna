"""Alembic async migration environment。

运行期数据库 URL 由部署环境通过 ``DNABY_DATABASE_URL`` 注入；测试可以通过
Alembic Config 覆盖空的配置项。这里不输出 URL，避免把凭据或私有路径写入日志。
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from src.infrastructure.persistence import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """读取调用方注入的 URL，并在缺失时显露配置错误。"""
    configured_url = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured_url:
        return configured_url

    environment_url = os.environ.get("DNABY_DATABASE_URL", "").strip()
    if environment_url:
        return environment_url

    raise RuntimeError(
        "Alembic requires sqlalchemy.url or the DNABY_DATABASE_URL environment variable"
    )


def run_migrations_offline() -> None:
    """在不建立连接时生成迁移 SQL。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在同步连接回调中配置 Alembic context。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建 async engine 并执行同步 migration 回调。"""
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口；Alembic 命令本身不持有现有 asyncio loop。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
