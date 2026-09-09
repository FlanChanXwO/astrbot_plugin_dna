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
ALIASES_DIR_NAME = "aliases"
CHAR_ALIAS_FILE_NAME = "char.json"
WEAPON_ALIAS_FILE_NAME = "weapon.json"
ID2NAME_FILE_NAME = "id2name.json"
RESOURCE_REPOSITORY_DIR_NAME = "repository"
RESOURCE_GENERATIONS_DIR_NAME = "generations"
RESOURCE_GENERATION_STATE_FILE_NAME = "current.json"
RESOURCE_LAST_SYNC_STATE_FILE_NAME = "last_sync.json"
RESOURCE_VALIDATION_STATE_FILE_NAME = "validation.json"


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
    def aliases_dir(self) -> Path:
        """角色和武器运行期别名目录。"""

        return self.state_dir / ALIASES_DIR_NAME

    @property
    def char_alias_path(self) -> Path:
        """角色别名运行期文件。"""

        return self.aliases_dir / CHAR_ALIAS_FILE_NAME

    @property
    def weapon_alias_path(self) -> Path:
        """武器别名运行期文件。"""

        return self.aliases_dir / WEAPON_ALIAS_FILE_NAME

    @property
    def id2name_path(self) -> Path:
        """角色和武器 ID 到名称的运行期索引文件。"""

        return self.aliases_dir / ID2NAME_FILE_NAME

    @property
    def resources_dir(self) -> Path:
        """公共资源仓库与 generation 目录。"""

        return self.data_dir / RESOURCES_DIR_NAME

    @property
    def resource_repository_dir(self) -> Path:
        """公共资源 Git 工作树目录。"""

        return self.resources_dir / RESOURCE_REPOSITORY_DIR_NAME

    @property
    def resource_generations_dir(self) -> Path:
        """已校验公共资源 generation 目录。"""

        return self.resources_dir / RESOURCE_GENERATIONS_DIR_NAME

    @property
    def resource_generation_state_path(self) -> Path:
        """当前公共资源 generation 指针文件。"""

        return self.resource_generations_dir / RESOURCE_GENERATION_STATE_FILE_NAME

    @property
    def resource_last_sync_state_path(self) -> Path:
        """最近一次公共资源同步状态文件。"""

        return self.resource_generations_dir / RESOURCE_LAST_SYNC_STATE_FILE_NAME

    @property
    def resource_validation_state_path(self) -> Path:
        """当前公共资源校验失败状态文件。"""

        return self.resource_generations_dir / RESOURCE_VALIDATION_STATE_FILE_NAME

    @property
    def cache_dir(self) -> Path:
        """可重建缓存目录。"""

        return self.data_dir / CACHE_DIR_NAME

    @property
    def backups_dir(self) -> Path:
        """状态迁移和客户端更新等备份目录。"""

        return self.data_dir / BACKUPS_DIR_NAME


__all__ = [
    "ALIASES_DIR_NAME",
    "BACKUPS_DIR_NAME",
    "CACHE_DIR_NAME",
    "CHAR_ALIAS_FILE_NAME",
    "DATABASE_DIR_NAME",
    "DATABASE_FILE_NAME",
    "ID2NAME_FILE_NAME",
    "RESOURCES_DIR_NAME",
    "RESOURCE_GENERATIONS_DIR_NAME",
    "RESOURCE_GENERATION_STATE_FILE_NAME",
    "RESOURCE_LAST_SYNC_STATE_FILE_NAME",
    "RESOURCE_REPOSITORY_DIR_NAME",
    "RESOURCE_VALIDATION_STATE_FILE_NAME",
    "STATE_DIR_NAME",
    "WEAPON_ALIAS_FILE_NAME",
    "RuntimeDataLayout",
]
