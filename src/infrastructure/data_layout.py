"""插件运行期数据目录布局。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DATABASE_DIR_NAME = "db"
DATABASE_FILE_NAME = "dna.sqlite3"
STATE_DIR_NAME = "state"
SUBSCRIPTIONS_FILE_NAME = "subscriptions.json"
SCHEDULER_STATE_FILE_NAME = "scheduler.json"
CLIENT_UPDATE_STATE_FILE_NAME = "client_update.json"
ANNOUNCEMENTS_DIR_NAME = "announcements"
ANNOUNCEMENT_SEEN_FILE_NAME = "seen.json"
ANNOUNCEMENT_DELIVERY_FILE_NAME = "delivery.json"
RESOURCES_DIR_NAME = "resources"
CACHE_DIR_NAME = "cache"
BACKUPS_DIR_NAME = "backups"
BACKUP_DATABASE_DIR_NAME = "database"
BACKUP_STATE_DIR_NAME = "state"
CLIENT_UPDATE_MIGRATION_BACKUP_FILE_NAME = "client_update.json.v2.bak"
ASSETS_DIR_NAME = "assets"
API_CACHE_DIR_NAME = "api"
RENDERED_CACHE_DIR_NAME = "rendered"
MEDIA_CACHE_DIR_NAME = "media"
GAME_AVATAR_DIR_NAME = "game_avatar"
USER_AVATAR_DIR_NAME = "user_avatar"
CUSTOM_DIR_NAME = "custom"
CUSTOM_PAINT_DIR_NAME = "custom_paint"
SIGN_DIR_NAME = "sign"
ANN_CARD_DIR_NAME = "ann_card"
CALENDAR_DIR_NAME = "calendar"
LOGIN_QR_DIR_NAME = "login_qr"
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
    def subscriptions_path(self) -> Path:
        """订阅持久化文件。"""

        return self.state_dir / SUBSCRIPTIONS_FILE_NAME

    @property
    def scheduler_state_path(self) -> Path:
        """内置调度状态文件。"""

        return self.state_dir / SCHEDULER_STATE_FILE_NAME

    @property
    def announcements_dir(self) -> Path:
        """公告已见与按目标投递状态目录。"""

        return self.state_dir / ANNOUNCEMENTS_DIR_NAME

    @property
    def ann_state_path(self) -> Path:
        """公告已见状态文件。"""

        return self.announcements_dir / ANNOUNCEMENT_SEEN_FILE_NAME

    @property
    def ann_delivery_state_path(self) -> Path:
        """公告按目标投递状态文件。"""

        return self.announcements_dir / ANNOUNCEMENT_DELIVERY_FILE_NAME

    @property
    def client_update_state_path(self) -> Path:
        """客户端更新基线与投递状态文件。"""

        return self.state_dir / CLIENT_UPDATE_STATE_FILE_NAME

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
    def cache_assets_dir(self) -> Path:
        """动态游戏素材缓存目录。"""

        return self.cache_dir / ASSETS_DIR_NAME

    @property
    def cache_game_avatar_dir(self) -> Path:
        """游戏角色头像缓存目录。"""

        return self.cache_assets_dir / GAME_AVATAR_DIR_NAME

    @property
    def cache_user_avatar_dir(self) -> Path:
        """事件用户头像缓存目录。"""

        return self.cache_assets_dir / USER_AVATAR_DIR_NAME

    @property
    def cache_custom_dir(self) -> Path:
        """自定义素材缓存目录。"""

        return self.cache_assets_dir / CUSTOM_DIR_NAME

    @property
    def cache_custom_paint_dir(self) -> Path:
        """自定义立绘缓存目录。"""

        return self.cache_custom_dir / CUSTOM_PAINT_DIR_NAME

    @property
    def cache_api_dir(self) -> Path:
        """外部 API 响应缓存目录。"""

        return self.cache_dir / API_CACHE_DIR_NAME

    @property
    def cache_rendered_dir(self) -> Path:
        """渲染卡片内容缓存与临时产物目录。"""

        return self.cache_dir / RENDERED_CACHE_DIR_NAME

    @property
    def cache_media_dir(self) -> Path:
        """公告、签到和日历等媒体缓存目录。"""

        return self.cache_dir / MEDIA_CACHE_DIR_NAME

    @property
    def cache_sign_dir(self) -> Path:
        """签到奖励图标缓存目录。"""

        return self.cache_media_dir / SIGN_DIR_NAME

    @property
    def cache_ann_card_dir(self) -> Path:
        """公告卡片媒体缓存目录。"""

        return self.cache_media_dir / ANN_CARD_DIR_NAME

    @property
    def cache_calendar_dir(self) -> Path:
        """活动日历媒体缓存目录。"""

        return self.cache_media_dir / CALENDAR_DIR_NAME

    @property
    def cache_login_qr_dir(self) -> Path:
        """登录二维码临时媒体目录。"""

        return self.cache_media_dir / LOGIN_QR_DIR_NAME

    @property
    def backups_dir(self) -> Path:
        """状态迁移和客户端更新等备份目录。"""

        return self.data_dir / BACKUPS_DIR_NAME

    @property
    def backups_database_dir(self) -> Path:
        """人工数据库备份目录。"""

        return self.backups_dir / BACKUP_DATABASE_DIR_NAME

    @property
    def backups_state_dir(self) -> Path:
        """状态迁移原始文件备份目录。"""

        return self.backups_dir / BACKUP_STATE_DIR_NAME

    @property
    def client_update_migration_backup_path(self) -> Path:
        """客户端更新 State v2 迁移的原始字节备份文件。"""

        return self.backups_state_dir / CLIENT_UPDATE_MIGRATION_BACKUP_FILE_NAME


__all__ = [
    "ALIASES_DIR_NAME",
    "ANNOUNCEMENT_DELIVERY_FILE_NAME",
    "ANNOUNCEMENT_SEEN_FILE_NAME",
    "ANNOUNCEMENTS_DIR_NAME",
    "ANN_CARD_DIR_NAME",
    "API_CACHE_DIR_NAME",
    "ASSETS_DIR_NAME",
    "BACKUP_DATABASE_DIR_NAME",
    "BACKUP_STATE_DIR_NAME",
    "BACKUPS_DIR_NAME",
    "CACHE_DIR_NAME",
    "CALENDAR_DIR_NAME",
    "CHAR_ALIAS_FILE_NAME",
    "CLIENT_UPDATE_MIGRATION_BACKUP_FILE_NAME",
    "CLIENT_UPDATE_STATE_FILE_NAME",
    "CUSTOM_DIR_NAME",
    "CUSTOM_PAINT_DIR_NAME",
    "DATABASE_DIR_NAME",
    "DATABASE_FILE_NAME",
    "GAME_AVATAR_DIR_NAME",
    "ID2NAME_FILE_NAME",
    "LOGIN_QR_DIR_NAME",
    "MEDIA_CACHE_DIR_NAME",
    "RENDERED_CACHE_DIR_NAME",
    "RESOURCES_DIR_NAME",
    "RESOURCE_GENERATIONS_DIR_NAME",
    "RESOURCE_GENERATION_STATE_FILE_NAME",
    "RESOURCE_LAST_SYNC_STATE_FILE_NAME",
    "RESOURCE_REPOSITORY_DIR_NAME",
    "RESOURCE_VALIDATION_STATE_FILE_NAME",
    "SCHEDULER_STATE_FILE_NAME",
    "SIGN_DIR_NAME",
    "STATE_DIR_NAME",
    "SUBSCRIPTIONS_FILE_NAME",
    "USER_AVATAR_DIR_NAME",
    "WEAPON_ALIAS_FILE_NAME",
    "RuntimeDataLayout",
]
