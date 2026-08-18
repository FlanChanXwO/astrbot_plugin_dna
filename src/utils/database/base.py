"""原生数据库基座：替代 gsucore ``GsCore.utils.database.*``。

- ``init_db`` / ``create_db_and_tables``：初始化插件私有 SQLite（sqlmodel + aiosqlite）。
- ``with_session``：类方法装饰器，自动打开/提交会话。
- ``Bind`` / ``User`` / ``BaseIDModel``：业务模型基类（与 gsucore 同名同语义）。

新装无需迁移；如需承接旧 gsucore 库，另行写迁移脚本（本移植默认全新开始）。
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select

_engine = None
_sessionmaker: async_sessionmaker | None = None
P = ParamSpec("P")
R = TypeVar("R")


def init_db(db_path: str | Path) -> None:
    """初始化引擎与会话工厂（main.py initialize 时调用）。"""
    global _engine, _sessionmaker
    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        future=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def create_db_and_tables() -> None:
    if _engine is None:
        raise RuntimeError("数据库未初始化: 请先调用 init_db")
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


def with_session(
    func: Callable[Concatenate[type[Any], AsyncSession, P], Awaitable[R]],
) -> Callable[Concatenate[type[Any], P], Awaitable[R]]:
    """把 ``async def f(cls, session, *args, **kwargs)`` 变为自动开/提交会话的类方法。"""

    @functools.wraps(func)
    async def wrapper(cls: type[Any], *args: P.args, **kwargs: P.kwargs) -> R:
        if _sessionmaker is None:
            raise RuntimeError("数据库未初始化: 请先调用 init_db")
        async with _sessionmaker() as session:
            result = await func(cls, session, *args, **kwargs)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result

    return cast(Callable[Concatenate[type[Any], P], Awaitable[R]], wrapper)


class BaseIDModel(SQLModel):
    id: int = Field(default=None, primary_key=True)


class Bind(SQLModel):
    """用户↔游戏 UID 绑定基类（多 UID 以 ``_`` 连接存于 ``uid``）。"""

    id: int = Field(default=None, primary_key=True)
    user_id: str = Field(default=None, title="用户id")
    bot_id: str = Field(default=None, title="botid")
    group_id: str | None = Field(default=None, title="群组id")
    uid: str = Field(default="", title="uid")
    bind_count: int = Field(default=0, title="绑定数量")

    # ---- 通用 CRUD ----
    @classmethod
    @with_session
    async def bind_exists(cls, session: AsyncSession, user_id: str, bot_id: str) -> bool:
        sql = select(cls).where(cls.user_id == user_id, cls.bot_id == bot_id)
        result = await session.execute(sql)
        return result.scalars().first() is not None

    @classmethod
    @with_session
    async def insert_data(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        **kwargs,
    ) -> int:
        obj = cls(user_id=user_id, bot_id=bot_id, **kwargs)
        session.add(obj)
        return 0

    @classmethod
    @with_session
    async def select_data(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> Bind | None:
        sql = select(cls).where(cls.user_id == user_id, cls.bot_id == bot_id)
        result = await session.execute(sql)
        return result.scalars().first()

    @classmethod
    @with_session
    async def update_data(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        **kwargs,
    ) -> int:
        obj = await cls.select_data(user_id=user_id, bot_id=bot_id)
        if obj is None:
            return -1
        for k, v in kwargs.items():
            setattr(obj, k, v)
        session.add(obj)
        return 0

    # ---- UID 列表操作 ----
    @classmethod
    @with_session
    async def get_uid_list_by_game(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> list[str]:
        result = await cls.select_data(user_id=user_id, bot_id=bot_id)
        if result is None:
            return []
        return list(dict.fromkeys(filter(None, result.uid.split("_"))))

    @classmethod
    @with_session
    async def get_uid_by_game(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> str | None:
        uid_list = await cls.get_uid_list_by_game(user_id=user_id, bot_id=bot_id)
        return uid_list[0] if uid_list else None

    @classmethod
    @with_session
    async def switch_uid_by_game(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> int:
        uid_list = await cls.get_uid_list_by_game(user_id=user_id, bot_id=bot_id)
        if uid not in uid_list:
            return -1
        uid_list.remove(uid)
        uid_list.insert(0, uid)
        return await cls.update_data(
            user_id=user_id,
            bot_id=bot_id,
            uid="_".join(uid_list),
        )


class User(SQLModel):
    """登录凭证基类。"""

    id: int = Field(default=None, primary_key=True)
    user_id: str = Field(default=None, title="用户id")
    bot_id: str = Field(default=None, title="botid")
    uid: str = Field(default=None, title="游戏uid")
    status: str = Field(default="", title="cookie状态")
    sign_switch: str = Field(default="", title="自动签到开关")

    @classmethod
    @with_session
    async def insert_data(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        **kwargs,
    ) -> int:
        obj = cls(user_id=user_id, bot_id=bot_id, **kwargs)
        session.add(obj)
        return 0

    @classmethod
    @with_session
    async def select_data(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> User | None:
        sql = select(cls).where(cls.user_id == user_id, cls.bot_id == bot_id)
        result = await session.execute(sql)
        return result.scalars().first()

    @classmethod
    @with_session
    async def select_data_list(
        cls,
        session: AsyncSession,
        user_id: str | None = None,
        bot_id: str | None = None,
        **filters,
    ) -> list[User]:
        conds = []
        if user_id is not None:
            conds.append(cls.user_id == user_id)
        if bot_id is not None:
            conds.append(cls.bot_id == bot_id)
        for k, v in filters.items():
            conds.append(getattr(cls, k) == v)
        sql = select(cls).where(*conds)
        result = await session.execute(sql)
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def update_data_by_uid(
        cls,
        session: AsyncSession,
        uid: str,
        bot_id: str,
        **kwargs,
    ) -> int:
        obj = await session.execute(
            select(cls).where(cls.uid == uid, cls.bot_id == bot_id)
        )
        record = obj.scalars().first()
        if record is None:
            return -1
        for k, v in kwargs.items():
            setattr(record, k, v)
        session.add(record)
        return 0

    @classmethod
    @with_session
    async def update_data_by_data(
        cls,
        session: AsyncSession,
        select_data: dict[str, Any],
        update_data: dict[str, Any],
    ) -> int:
        sql = select(cls).where(
            *[getattr(cls, k) == v for k, v in select_data.items()]
        )
        result = await session.execute(sql)
        records = result.scalars().all()
        for record in records:
            for k, v in update_data.items():
                setattr(record, k, v)
            session.add(record)
        return 0
