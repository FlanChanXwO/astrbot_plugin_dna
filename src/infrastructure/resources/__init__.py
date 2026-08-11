"""私有资源仓库的 manifest、路径和 Git 同步入口。"""

from .git import (
    DEFAULT_RESOURCE_REMOTE,
    GitCommandError,
    GitCommandResult,
    GitUnavailableError,
    ResourceLocalChangesError,
    ResourceRemoteMismatchError,
    ResourceSyncError,
    ResourceSynchronizer,
    ResourceSyncResult,
    download_all_resources,
    run_git,
)
from .encyclopedia import (
    AliasCatalog,
    EncyclopediaResourceError,
    EncyclopediaResourceStore,
    GuideAsset,
)
from .manifest import ResourceManifest, ResourceManifestError
from .paths import (
    PLUGIN_NAME,
    RESOURCE_REPOSITORY_NAME,
    default_resource_repository_dir,
    resource_repository_dir,
)

__all__ = [
    "DEFAULT_RESOURCE_REMOTE",
    "AliasCatalog",
    "EncyclopediaResourceError",
    "EncyclopediaResourceStore",
    "GuideAsset",
    "PLUGIN_NAME",
    "RESOURCE_REPOSITORY_NAME",
    "GitCommandError",
    "GitCommandResult",
    "GitUnavailableError",
    "ResourceLocalChangesError",
    "ResourceManifest",
    "ResourceManifestError",
    "ResourceRemoteMismatchError",
    "ResourceSyncError",
    "ResourceSyncResult",
    "ResourceSynchronizer",
    "default_resource_repository_dir",
    "download_all_resources",
    "resource_repository_dir",
    "run_git",
]
