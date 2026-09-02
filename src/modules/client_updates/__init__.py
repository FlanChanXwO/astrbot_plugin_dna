"""客户端更新查询与定时推送领域。"""

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateStructureError,
    ClientUpdateTransport,
    ClientUpdateTransportError,
    ClientVersion,
    ClientVersionSnapshot,
    parse_version_list,
    parse_version_list_entries,
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
    "ClientUpdateFailureKind",
    "ClientUpdateObservation",
    "ClientUpdateStateError",
    "ClientUpdateStateStore",
    "ClientUpdatePatchSizeError",
    "ClientUpdateRollbackError",
    "ClientUpdateService",
    "ClientUpdateStructureError",
    "ClientUpdateTransport",
    "ClientUpdateTransportError",
    "ClientVersion",
    "ClientVersionSnapshot",
    "parse_version_list",
    "parse_version_list_entries",
    "sum_patch_file_sizes",
]
