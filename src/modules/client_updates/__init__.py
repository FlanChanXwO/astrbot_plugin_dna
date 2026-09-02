"""客户端更新查询与定时推送领域。"""

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateStructureError,
    ClientVersion,
    ClientVersionSnapshot,
    parse_version_list,
    sum_patch_file_sizes,
)

__all__ = [
    "ClientPlatform",
    "ClientRegion",
    "ClientUpdateStructureError",
    "ClientVersion",
    "ClientVersionSnapshot",
    "parse_version_list",
    "sum_patch_file_sizes",
]
