"""客户端更新查询与定时推送领域。"""

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateStructureError,
    ClientVersion,
    ClientVersionSnapshot,
    parse_version_list,
    sum_patch_file_sizes,
)
from .state import (
    STATE_VERSION,
    ClientUpdateBaseline,
    ClientUpdateStateError,
    ClientUpdateStateStore,
)
from .service import (
    ClientUpdatePatchSizeError,
    ClientUpdateRollbackError,
    ClientUpdateService,
)

__all__ = [
    "STATE_VERSION",
    "ClientPlatform",
    "ClientRegion",
    "ClientUpdateBaseline",
    "ClientUpdateChange",
    "ClientUpdateStateError",
    "ClientUpdateStateStore",
    "ClientUpdatePatchSizeError",
    "ClientUpdateRollbackError",
    "ClientUpdateService",
    "ClientUpdateStructureError",
    "ClientVersion",
    "ClientVersionSnapshot",
    "parse_version_list",
    "sum_patch_file_sizes",
]
