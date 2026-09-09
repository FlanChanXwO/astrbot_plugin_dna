"""插件运行期数据目录布局。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DATABASE_DIR_NAME = "db"
DATABASE_FILE_NAME = "dna.sqlite3"
STATE_DIR_NAME = "state"
RESOURCES_DIR_NAME = "resources"
CACHE_DIR_NAME = "cache"
BACKUPS_DIR_NAME = "backups"


@dataclass(frozen=True, slots=True)
class RuntimeDataLayout:
    """集中描述插件运行期数据根及其稳定的一级目录。"""

    data_dir: Path

    def __post_init__(self) -> None:
        """统一外部传入路径，构造阶段不创建文件系统对象。"""

        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> RuntimeDataLayout:
        """从字符串或路径构造运行期数据布局。"""

        return cls(Path(data_dir))

    @property
    def db_dir(self) -> Path:
        """数据库目录。"""

        return self.data_dir / DATABASE_DIR_NAME

    @property
    def database_path(self) -> Path:
        """插件 SQLite 数据库文件路径。"""

        return self.db_dir / DATABASE_FILE_NAME

    @property
    def state_dir(self) -> Path:
        """订阅、调度、公告和别名等可恢复状态目录。"""

        return self.data_dir / STATE_DIR_NAME

    @property
    def resources_dir(self) -> Path:
        """公共资源仓库与 generation 目录。"""

        return self.data_dir / RESOURCES_DIR_NAME

    @property
    def cache_dir(self) -> Path:
        """可重建缓存目录。"""

        return self.data_dir / CACHE_DIR_NAME

    @property
    def backups_dir(self) -> Path:
        """状态迁移和客户端更新等备份目录。"""

        return self.data_dir / BACKUPS_DIR_NAME


__all__ = [
    "BACKUPS_DIR_NAME",
    "CACHE_DIR_NAME",
    "DATABASE_DIR_NAME",
    "DATABASE_FILE_NAME",
    "RESOURCES_DIR_NAME",
    "STATE_DIR_NAME",
    "RuntimeDataLayout",
]
