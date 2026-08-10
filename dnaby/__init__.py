"""dnaby —— 二重螺旋业务包（由 GsCore 插件 DNAUID 原生移植）。

AstrBot 插件的命令触发/发送/配置/DB/订阅均走 AstrBot 原生 API，
本包仅保留原业务纯逻辑与适配后的处理器。
"""

from .version import DNAUID_version as __version__

__all__ = ["__version__"]
