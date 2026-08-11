"""命令模块唯一显式索引。

新增命令必须先在这里登记模块；不通过目录扫描，也不会因为 legacy 文件仍
存在而自动把尚未迁移的能力注册到 AstrBot。
"""

from types import ModuleType

from . import help as help_module
from .account import commands as account_module
from .encyclopedia import commands as encyclopedia_module
from .player import commands as player_module
from .privacy import commands as privacy_module

COMMAND_MODULES: tuple[ModuleType, ...] = (
    help_module,
    account_module,
    player_module,
    privacy_module,
    encyclopedia_module,
)


__all__ = ["COMMAND_MODULES"]
