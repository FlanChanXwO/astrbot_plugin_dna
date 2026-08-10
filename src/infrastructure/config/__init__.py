"""插件 typed 配置和 AstrBot schema 生成入口。"""

from .schema import generate_astrbot_schema, write_astrbot_schema
from .settings import (
    DisplaySettings,
    DnabySettings,
    LoginSettings,
    NetworkSettings,
    NotificationSettings,
    SignInSettings,
)

__all__ = [
    "DisplaySettings",
    "DnabySettings",
    "LoginSettings",
    "NetworkSettings",
    "NotificationSettings",
    "SignInSettings",
    "generate_astrbot_schema",
    "write_astrbot_schema",
]

