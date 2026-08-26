"""插件 typed 配置和 AstrBot schema 生成入口。"""

from .legacy import (
    CONFIG_DEFAULT,
    DNA_PREFIX,
    DNAConfig,
    DNASignConfig,
)
from .legacy import (
    generate_astrbot_schema as generate_legacy_schema,
)
from .schema import generate_astrbot_schema, write_astrbot_schema
from .settings import (
    DisplaySettings,
    DnabySettings,
    LoginSettings,
    NetworkSettings,
    NotificationSettings,
    SignInSettings,
    migrate_config_dict,
)

__all__ = [
    "CONFIG_DEFAULT",
    "DNA_PREFIX",
    "DNAConfig",
    "DNASignConfig",
    "DisplaySettings",
    "DnabySettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "SignInSettings",
    "generate_astrbot_schema",
    "generate_legacy_schema",
    "migrate_config_dict",
    "write_astrbot_schema",
]
