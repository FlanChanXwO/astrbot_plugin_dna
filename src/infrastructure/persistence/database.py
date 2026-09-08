"""SQLAlchemy async engine、session 和事务边界。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


class AsyncDatabase:
    """封装新数据库的连接和显式事务入口。"""

    def __init__(self, path: str | Path, *, echo: bool = False) -> None:
        self.path = Path(path).expanduser().resolve()
        self._url = f"sqlite+aiosqlite:///{self.path}"
        self.engine: AsyncEngine = create_async_engine(self._url, echo=echo)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        # SQLite 的可空作用域需要应用内串行化 upsert；并发 SELECT 后 INSERT
        # 会绕过普通三列 UNIQUE（多个 NULL 可共存），实测会留下重复全局隐私行。
        self._write_lock = asyncio.Lock()

    @property
    def url(self) -> str:
        """返回用于创建 engine 的 async SQLite URL。"""
        return self._url

    @classmethod
    def from_data_dir(
        cls, data_dir: str | Path, *, echo: bool = False
    ) -> AsyncDatabase:
        """从运行期 data 目录定位新数据库，不读取旧 `dnaby.db`。"""
        return cls(Path(data_dir) / "dnaby.sqlite3", echo=echo)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """提供不隐式提交的 session；写操作必须使用 :meth:`transaction`。"""
        async with self.session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """统一处理一次事务的提交、回滚和 session 释放。"""
        async with self._write_lock:
            session = self.session_factory()
            try:
                async with session.begin():
                    yield session
            except BaseException:
                # session.begin 已覆盖通常异常；这里显式处理取消等 BaseException，确保
                # 未来新增的事务调用点不会把半成品事务留给连接池。
                await session.rollback()
                raise
            finally:
                await session.close()

    async def create_schema_for_tests(self) -> None:
        """仅为隔离测试建立 metadata schema，生产变更必须走 Alembic。"""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """释放连接池资源。"""
        await self.engine.dispose()


__all__ = ["AsyncDatabase"]
