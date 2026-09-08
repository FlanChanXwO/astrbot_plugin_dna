"""运行期资源仓库路径。"""

from __future__ import annotations

from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_dnaby"
RESOURCE_REPOSITORY_NAME = "resources"
RESOURCE_GENERATIONS_NAME = "resource_generations"
RESOURCE_GENERATION_STATE_NAME = "current.json"
RESOURCE_LAST_SYNC_STATE_NAME = "last_sync.json"
RESOURCE_VALIDATION_STATE_NAME = "validation.json"


def resource_repository_dir(data_dir: str | Path) -> Path:
    """在插件运行期数据目录下返回资源仓库目录，不主动创建目录。"""

    return Path(data_dir) / RESOURCE_REPOSITORY_NAME


def resource_generations_dir(data_dir: str | Path) -> Path:
    """返回公共资源 generation 的专用运行期目录。"""

    return Path(data_dir) / RESOURCE_GENERATIONS_NAME


def resource_generation_state_path(data_dir: str | Path) -> Path:
    """返回原子替换的当前 generation 指针文件路径。"""

    return resource_generations_dir(data_dir) / RESOURCE_GENERATION_STATE_NAME


def resource_last_sync_state_path(data_dir: str | Path) -> Path:
    """返回最近一次资源同步结果的运行期状态文件路径。"""

    return resource_generations_dir(data_dir) / RESOURCE_LAST_SYNC_STATE_NAME


def resource_validation_state_path(data_dir: str | Path) -> Path:
    """返回当前 generation 最近一次校验失败摘要的路径。"""

    return resource_generations_dir(data_dir) / RESOURCE_VALIDATION_STATE_NAME


def default_resource_repository_dir(plugin_name: str = PLUGIN_NAME) -> Path:
    """使用 AstrBot ``StarTools.get_data_dir`` 解析插件数据目录。"""

    from astrbot.api.star import StarTools

    return resource_repository_dir(StarTools.get_data_dir(plugin_name))


__all__ = [
    "PLUGIN_NAME",
    "RESOURCE_GENERATIONS_NAME",
    "RESOURCE_GENERATION_STATE_NAME",
    "RESOURCE_LAST_SYNC_STATE_NAME",
    "RESOURCE_REPOSITORY_NAME",
    "RESOURCE_VALIDATION_STATE_NAME",
    "default_resource_repository_dir",
    "resource_generation_state_path",
    "resource_generations_dir",
    "resource_last_sync_state_path",
    "resource_validation_state_path",
    "resource_repository_dir",
]
