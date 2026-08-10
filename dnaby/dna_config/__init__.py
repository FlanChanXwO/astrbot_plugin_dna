"""配置包入口：导出配置管理器实例与 core 配置访问。

替代 gsucore 的 ``Plugins`` / ``get_plugin_available_prefix``：
AstrBot 命令为正则触发、无固定前缀，故 ``DNA_PREFIX`` 恒为空。
"""

from .config_manager import (
    bind_core_config,
    get_core_config,
)
from .dna_config import DNAConfig, DNASignConfig


def generate_astrbot_schema() -> dict:
    """合并两套配置生成 ``_conf_schema.json`` 内容。"""
    schema = {}
    schema.update(DNAConfig.generate_astrbot_schema())
    schema.update(DNASignConfig.generate_astrbot_schema())
    return schema


DNA_PREFIX = ""


__all__ = [
    "DNA_PREFIX",
    "DNAConfig",
    "DNASignConfig",
    "bind_core_config",
    "generate_astrbot_schema",
    "get_core_config",
]
