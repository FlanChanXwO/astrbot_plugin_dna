"""生产数据库 schema 迁移入口。

Alembic 是生产 schema 的唯一事实来源：插件启动时必须先执行 ``upgrade head``，
之后账号、Dashboard、签到和公告等消费者才能访问数据库。这里不提供
``create_all()`` 回退路径，缺失的 Alembic 资产必须显式启动失败，否则发布打包
错误会被静默隐藏。

存在一个退化形态：业务表已经是当前 head 结构，但 ``alembic_version`` 缺失。
这只会由绕过迁移直接建表的工具产生（例如 ``scripts/test_live_all_commands.py``
对真实数据目录调用 ``create_schema_for_tests``）。此时直接 ``upgrade head`` 会因
“表已存在”永远无法启动。这里在**逐项比对确认表结构与 head 完全一致后**把它接管
为 head（``stamp``）；比对不通过则显式失败，不猜测、不修改 schema。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

from ..logger import logger
from .database import AsyncDatabase
from .models import Base

ALEMBIC_CONFIG_FILE_NAME = "alembic.ini"
ALEMBIC_SCRIPTS_DIR_NAME = "alembic"


def default_plugin_root() -> Path:
    """返回包含 ``alembic.ini`` 的插件根目录，不依赖当前工作目录。"""

    return Path(__file__).resolve().parents[3]


def _touches_plugin_schema(difference: Any) -> bool:
    """判断一条 ``compare_metadata`` 差异是否涉及本插件自己的 schema。

    数据库里多出的无关表不影响“本插件表结构是否等于 head”的判定，因此
    类型为 ``remove_table`` 且表名不在 metadata 中时忽略；其余差异（缺表、
    缺列、多列、类型变化、约束变化）都会阻止自动接管。
    """

    if not isinstance(difference, tuple) or not difference:
        return True
    kind = difference[0]
    if kind == "remove_table":
        table = difference[1]
        return getattr(table, "name", None) in Base.metadata.tables
    if kind == "add_table":
        return True
    # 列/约束级差异的第 3 项是表名。
    table_name = difference[2] if len(difference) > 2 else None
    return table_name is None or table_name in Base.metadata.tables


class DatabaseMigration:
    """把插件自带 Alembic 目录升级到 head，并保证单实例幂等。"""

    def __init__(self, database: AsyncDatabase, *, plugin_root: Path) -> None:
        self.database = database
        self.plugin_root = Path(plugin_root).expanduser().resolve()
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def initialized(self) -> bool:
        """返回本次实例是否已成功完成迁移。"""

        return self._initialized

    async def initialize(self) -> None:
        """执行一次 ``alembic upgrade head``；失败时保持未初始化并向上抛出。"""

        async with self._lock:
            if self._initialized:
                return
            config = self._build_config()
            # alembic/env.py 在线模式内部自行 ``asyncio.run``，因此不能在
            # AstrBot 已运行的事件循环里直接调用，必须放到独立线程。
            try:
                if await asyncio.to_thread(self._should_adopt_untracked_schema):
                    # 表结构与 head 完全一致，只是没有版本记录；先接管再 upgrade。
                    await asyncio.to_thread(command.stamp, config, "head")
                    logger.warning(
                        "检测到未跟踪但结构匹配的数据库 schema，已接管为 head=%s",
                        self.current_head(),
                    )
                await asyncio.to_thread(command.upgrade, config, "head")
            except Exception as error:
                # fail-fast：不吞异常、不把数据库 URL 拼进日志，让生命周期中止启动。
                logger.error(
                    "数据库迁移失败 kind=%s",
                    type(error).__name__,
                )
                raise
            self._initialized = True
            logger.info("数据库 schema 已准备完成 head=%s", self.current_head())

    def current_head(self) -> str:
        """返回代码中当前 Alembic head revision，供诊断与验收使用。

        Raises:
            RuntimeError: 版本目录没有任何 revision；此时 schema 无法被追踪。
        """

        head = ScriptDirectory.from_config(self._build_config()).get_current_head()
        if head is None:
            raise RuntimeError("alembic 版本目录中没有可用 revision")
        return head

    def _should_adopt_untracked_schema(self) -> bool:
        """判断是否应把“无版本记录但结构匹配”的库接管为 head。

        在线程中同步执行，避免 aiosqlite 与 Alembic 的循环冲突。仅在
        ``alembic_version`` 缺失且至少已存在一张业务表时才会比对，其余情况返回
        ``False`` 交由正常 ``upgrade`` 处理。

        Raises:
            RuntimeError: 未跟踪库的表结构与 head 不一致；不得猜测或自动改写。
        """

        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine, inspect

        # Alembic 在同步连接上运行比对；这里用同一文件的同步驱动。
        engine = create_engine(f"sqlite:///{self.database.path}")
        try:
            with engine.connect() as connection:
                table_names = set(inspect(connection).get_table_names())
                if "alembic_version" in table_names:
                    return False
                if not any(name in table_names for name in Base.metadata.tables):
                    # 全新（或空）数据库：交给正常 upgrade 建表。
                    return False
                context = MigrationContext.configure(
                    connection,
                    opts={"compare_type": True},
                )
                differences = [
                    difference
                    for difference in compare_metadata(context, Base.metadata)
                    if _touches_plugin_schema(difference)
                ]
        finally:
            engine.dispose()

        if differences:
            logger.error(
                "未跟踪数据库 schema 与 head 不一致差异数=%d",
                len(differences),
            )
            raise RuntimeError(
                "检测到未跟踪的数据库 schema 与当前版本不一致；"
                "请先备份数据库并手动处理（例如核对后执行 alembic stamp/upgrade），"
                "插件已拒绝启动以避免误改数据"
            )
        return True

    def _build_config(self) -> Config:
        """构造绝对路径的 Alembic 配置，并注入当前数据库 URL。"""

        config_path = self.plugin_root / ALEMBIC_CONFIG_FILE_NAME
        script_location = self.plugin_root / ALEMBIC_SCRIPTS_DIR_NAME
        versions_dir = script_location / "versions"
        if not config_path.is_file() or not (script_location / "env.py").is_file():
            raise FileNotFoundError(
                "alembic 资产缺失，无法初始化数据库 schema"
            )
        if not versions_dir.is_dir() or not any(versions_dir.glob("*.py")):
            raise FileNotFoundError("alembic versions 目录缺失或为空")

        config = Config(str(config_path))
        config.set_main_option("script_location", str(script_location))
        # 不写 DNA_DATABASE_URL，避免同进程多实例通过环境变量互相污染。
        config.set_main_option("sqlalchemy.url", self.database.url)
        return config


__all__ = ["DatabaseMigration", "default_plugin_root"]
