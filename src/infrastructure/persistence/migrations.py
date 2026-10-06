"""生产数据库 schema 迁移入口。

Alembic 是生产 schema 的唯一事实来源：插件启动时必须先执行 ``upgrade head``，
之后账号、Dashboard、签到和公告等消费者才能访问数据库。这里不提供
``create_all()`` 回退路径，缺失的 Alembic 资产必须显式启动失败，否则发布打包
错误会被静默隐藏。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

from ..logger import logger
from .database import AsyncDatabase

ALEMBIC_CONFIG_FILE_NAME = "alembic.ini"
ALEMBIC_SCRIPTS_DIR_NAME = "alembic"


def default_plugin_root() -> Path:
    """返回包含 ``alembic.ini`` 的插件根目录，不依赖当前工作目录。"""

    return Path(__file__).resolve().parents[3]


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
        """返回代码中当前 Alembic head revision，供诊断与验收使用。"""

        return ScriptDirectory.from_config(self._build_config()).get_current_head()

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
