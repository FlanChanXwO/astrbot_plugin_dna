"""插件 typed 配置和 AstrBot schema 生成入口。"""

from .legacy import (
    CONFIG_DEFAULT,
    DNA_PREFIX,
    DNAConfig,
    DNASignConfig,
)
from .schema import generate_astrbot_schema, write_astrbot_schema
from .settings import (
    AgentToolsSettings,
    AISettings,
    CacheSettings,
    ClientUpdatesSettings,
    DisplaySettings,
    DNASettings,
    GeneralSettings,
    LoginSettings,
    NetworkSettings,
    NotificationSettings,
    ResourceSettings,
    SignInSettings,
    migrate_config_dict,
)

__all__ = [
    "CONFIG_DEFAULT",
    "DNA_PREFIX",
    "AISettings",
    "AgentToolsSettings",
    "CacheSettings",
    "ClientUpdatesSettings",
    "DNAConfig",
    "DNASettings",
    "DNASignConfig",
    "DisplaySettings",
    "GeneralSettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "ResourceSettings",
    "SignInSettings",
    "generate_astrbot_schema",
    "migrate_config_dict",
    "write_astrbot_schema",
]
