"""插件统一日志入口。

源码统一依赖本模块，而不是直接绑定 AstrBot 或 Python 标准库日志实现。
平台适配只保留在这一处，便于后续调整而不扩散宿主 API 依赖。
"""

from astrbot.api import logger as _astrbot_logger

logger = _astrbot_logger

__all__ = ["logger"]
