"""客户端更新查询与定时推送领域。"""

from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateFailureKind,
    ClientUpdateObservation,
    ClientUpdateRequest,
    ClientUpdateStructureError,
    ClientUpdateTransport,
    ClientUpdateTransportError,
    ClientVersion,
    ClientVersionSnapshot,
    normalize_client_update_platforms,
    parse_version_list,
    parse_version_list_entries,
    sum_patch_file_sizes,
)
from .delivery import (
    ClientUpdateDeliveryService,
    ClientUpdatePush,
    ClientUpdatePushAdapter,
    ClientUpdatePushMessage,
    ClientUpdatePushPort,
    ClientUpdatePushTarget,
)
from .service import (
    ClientUpdatePatchSizeError,
    ClientUpdateRollbackError,
    ClientUpdateService,
)
from .state import (
    STATE_VERSION,
    ClientUpdateBaseline,
    ClientUpdateStateError,
    ClientUpdateStateStore,
)

__all__ = [
    "STATE_VERSION",
    "ClientPlatform",
    "ClientRegion",
    "ClientUpdateBaseline",
    "ClientUpdateChange",
    "ClientUpdateDeliveryService",
    "ClientUpdateFailureKind",
    "ClientUpdateObservation",
    "ClientUpdatePatchSizeError",
    "ClientUpdatePush",
    "ClientUpdatePushAdapter",
    "ClientUpdatePushMessage",
    "ClientUpdatePushPort",
    "ClientUpdatePushTarget",
    "ClientUpdateRequest",
    "ClientUpdateRollbackError",
    "ClientUpdateService",
    "ClientUpdateStateError",
    "ClientUpdateStateStore",
    "ClientUpdateStructureError",
    "ClientUpdateTransport",
    "ClientUpdateTransportError",
    "ClientVersion",
    "ClientVersionSnapshot",
    "normalize_client_update_platforms",
    "parse_version_list",
    "parse_version_list_entries",
    "sum_patch_file_sizes",
]
