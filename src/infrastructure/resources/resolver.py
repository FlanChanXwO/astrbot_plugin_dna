"""generation-first 的运行期图片素材解析。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

from PIL import Image

if TYPE_CHECKING:
    from .generation import ResourceSnapshotCoordinator


AssetKind: TypeAlias = Literal["role_avatar", "role_paint", "weapon"]
AssetSource: TypeAlias = Literal[
    "verified_snapshot",
    "dynamic_cache",
    "download",
    "none",
]
AssetStatus: TypeAlias = Literal["provided", "missing"]


class AssetResolutionError(OSError):
    """素材候选不安全或下载后没有得到可用图片。"""


class AssetDownloader(Protocol):
    """图片下载器的最小异步接口；具体并发策略由后续下载器 task 管理。"""

    async def fetch(self, url: str, target: Path, *, tag: str = "") -> Path | None:
        """把一个 URL 写入目标缓存文件。"""


DownloadCallable: TypeAlias = Callable[[str, Path], Awaitable[Path | None]]
Downloader: TypeAlias = AssetDownloader | DownloadCallable


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """一个素材请求的解析结果及其来源元数据。"""

    path: Path | None
    source: AssetSource
    status: AssetStatus
    incomplete: bool
    kind: str = ""
    asset_id: str = ""

    @property
    def logical_key(self) -> str:
        """返回不包含绝对路径的稳定逻辑 key。"""

        if not self.kind or not self.asset_id:
            return ""
        return f"image:{self.kind}:{self.asset_id}"

    @property
    def layer(self) -> str:
        """返回便于观测的 L1/L2/网络层名称。"""

        return {
            "verified_snapshot": "L1",
            "dynamic_cache": "L2",
            "download": "network",
            "none": "none",
        }[self.source]

    @property
    def is_l1(self) -> bool:
        return self.source == "verified_snapshot"

    @property
    def is_l2(self) -> bool:
        return self.source == "dynamic_cache"

    @property
    def was_downloaded(self) -> bool:
        return self.source == "download"


@dataclass(frozen=True, slots=True)
class _AssetSpec:
    """一个逻辑素材类型在公共资源和动态缓存中的路径契约。"""

    snapshot_template: str
    cache_directory: str
    cache_filename: str


_ASSET_SPECS: dict[str, _AssetSpec] = {
    "role_avatar": _AssetSpec(
        snapshot_template="images/role_avatar/{id}.png",
        cache_directory="game_avatar",
        cache_filename="avatar_{id}.png",
    ),
    "role_paint": _AssetSpec(
        snapshot_template="images/role_paint/{id}.png",
        cache_directory="paint",
        cache_filename="paint_{id}.png",
    ),
    "weapon": _AssetSpec(
        snapshot_template="images/weapon/{id}.png",
        cache_directory="weapon",
        cache_filename="weapon_{id}.png",
    ),
}

_KIND_ALIASES = {
    "avatar": "role_avatar",
    "role-avatar": "role_avatar",
    "paint": "role_paint",
    "role-paint": "role_paint",
    "weapon_icon": "weapon",
    "weapon-icon": "weapon",
}


def _absolute_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    return Path(path).expanduser().absolute()


def _normalize_identifier(asset_id: str | int) -> str:
    identifier = str(asset_id).strip()
    if (
        not identifier
        or identifier in {".", ".."}
        or "/" in identifier
        or "\\" in identifier
        or any(part in {".", ".."} for part in PurePosixPath(identifier).parts)
    ):
        raise ValueError("素材 ID 必须是单一安全路径片段")
    return identifier


def _normalize_kind(kind: str) -> str:
    normalized = str(kind).strip().casefold()
    normalized = _KIND_ALIASES.get(normalized, normalized)
    if normalized not in _ASSET_SPECS:
        raise ValueError(f"不支持的图片素材类型: {kind!r}")
    return normalized


def _parse_logical_request(kind: str, asset_id: str | int | None) -> tuple[str, str]:
    """接受类型+ID，也接受 ``image:<kind>:<id>`` 逻辑 key。"""

    if asset_id is not None:
        return _normalize_kind(kind), _normalize_identifier(asset_id)

    raw = str(kind).strip()
    parts = raw.split(":", 2)
    if len(parts) == 3 and parts[0] in {"image", "asset"}:
        return _normalize_kind(parts[1]), _normalize_identifier(parts[2])
    parts = raw.split("/", 2)
    if len(parts) == 2:
        return _normalize_kind(parts[0]), _normalize_identifier(parts[1])
    raise ValueError("素材请求必须同时提供类型和 ID，或使用 image:<kind>:<id>")


def _verified_file(root: Path | None, relative_path: str) -> Path | None:
    """返回 root 内的普通文件；缺失、符号链接和越界路径均不接受。"""

    if root is None or root.is_symlink() or not root.is_dir():
        return None
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise AssetResolutionError("公共资源相对路径不安全")

    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            return None
    if not candidate.is_file():
        return None
    try:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved_candidate.is_relative_to(resolved_root):
        return None
    return candidate


def _is_valid_image(path: Path) -> bool:
    """完整校验图片，避免把损坏文件当作 L1/L2 命中。"""

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return False
    return True


class AssetResolver:
    """按当前 generation → 动态缓存 → 网络下载解析图片素材。

    当传入 ``coordinator`` 时，每次 ``resolve`` 都会在 coordinator 的
    ``optional_lease`` 内读取 L1；调用方也可以使用 ``bind`` 把多个素材请求
    固定在同一个 generation lease 中。L1 始终只读，下载结果只写入 L2。
    """

    def __init__(
        self,
        *,
        dynamic_root: str | Path | None = None,
        cache_root: str | Path | None = None,
        snapshot_root: str | Path | None = None,
        coordinator: ResourceSnapshotCoordinator | None = None,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        if dynamic_root is not None and cache_root is not None:
            if _absolute_path(dynamic_root) != _absolute_path(cache_root):
                raise ValueError("dynamic_root 与 cache_root 不能指向不同目录")
        resolved_dynamic_root = dynamic_root if dynamic_root is not None else cache_root
        if resolved_dynamic_root is None:
            raise TypeError("AssetResolver 需要 dynamic_root")
        if coordinator is not None and resource_snapshots is not None:
            raise ValueError("coordinator 与 resource_snapshots 只能提供一个")

        self.dynamic_root = _absolute_path(resolved_dynamic_root)
        assert self.dynamic_root is not None
        self.snapshot_root = _absolute_path(snapshot_root)
        self.coordinator = coordinator or resource_snapshots
        self.downloader = downloader

    @classmethod
    def from_snapshot(
        cls,
        snapshot: object | None,
        *,
        dynamic_root: str | Path,
        downloader: Downloader | None = None,
    ) -> AssetResolver:
        """从一个已持有的 generation snapshot 创建请求级 resolver。"""

        root = None if snapshot is None else getattr(snapshot, "root", None)
        return cls(
            snapshot_root=root,
            dynamic_root=dynamic_root,
            downloader=downloader,
        )

    @property
    def l2_root(self) -> Path:
        """返回动态游戏素材缓存根目录。"""

        return self.dynamic_root

    def cache_path(self, kind: str, asset_id: str | int) -> Path:
        """返回指定素材的 L2 目标，不创建目录。"""

        normalized_kind = _normalize_kind(kind)
        identifier = _normalize_identifier(asset_id)
        spec = _ASSET_SPECS[normalized_kind]
        return (
            self.dynamic_root
            / spec.cache_directory
            / spec.cache_filename.format(
                id=identifier,
            )
        )

    def snapshot_path(self, kind: str, asset_id: str | int) -> Path:
        """返回指定素材在 generation 内的相对路径投影。"""

        normalized_kind = _normalize_kind(kind)
        identifier = _normalize_identifier(asset_id)
        return Path(
            _ASSET_SPECS[normalized_kind].snapshot_template.format(id=identifier),
        )

    @contextmanager
    def bind(self) -> Iterator[AssetResolver]:
        """固定一个请求期 generation lease，供多个素材读取共同使用。"""

        if self.coordinator is None:
            yield self
            return
        with self.coordinator.optional_lease() as snapshot:
            yield AssetResolver.from_snapshot(
                snapshot,
                dynamic_root=self.dynamic_root,
                downloader=self.downloader,
            )

    async def resolve(
        self,
        kind: str,
        asset_id: str | int | None = None,
        *,
        url: str | None = None,
    ) -> ResolvedAsset:
        """解析一个素材；本地双 miss 且有 URL 时才提交网络下载。"""

        normalized_kind, identifier = _parse_logical_request(kind, asset_id)
        if self.coordinator is None:
            return await self._resolve_with_snapshot(
                self.snapshot_root,
                normalized_kind,
                identifier,
                url=url,
            )

        # 下载也处于同一个 lease 内，确保一次解析不会跨 generation 混读。
        with self.coordinator.optional_lease() as snapshot:
            snapshot_root = None if snapshot is None else snapshot.root
            return await self._resolve_with_snapshot(
                snapshot_root,
                normalized_kind,
                identifier,
                url=url,
            )

    async def resolve_asset(
        self,
        kind: str,
        asset_id: str | int | None = None,
        *,
        url: str | None = None,
    ) -> ResolvedAsset:
        """``resolve`` 的语义别名，方便调用方表达素材请求。"""

        return await self.resolve(kind, asset_id, url=url)

    async def resolve_role_avatar(
        self, char_id: str | int, url: str | None = None
    ) -> ResolvedAsset:
        return await self.resolve("role_avatar", char_id, url=url)

    async def resolve_role_paint(
        self, char_id: str | int, url: str | None = None
    ) -> ResolvedAsset:
        return await self.resolve("role_paint", char_id, url=url)

    async def resolve_weapon(
        self, weapon_id: str | int, url: str | None = None
    ) -> ResolvedAsset:
        return await self.resolve("weapon", weapon_id, url=url)

    async def _resolve_with_snapshot(
        self,
        snapshot_root: Path | None,
        kind: str,
        identifier: str,
        *,
        url: str | None,
    ) -> ResolvedAsset:
        spec = _ASSET_SPECS[kind]
        snapshot_relative = spec.snapshot_template.format(id=identifier)
        snapshot_path = _verified_file(snapshot_root, snapshot_relative)
        if snapshot_path is not None and _is_valid_image(snapshot_path):
            return self._result(
                snapshot_path,
                "verified_snapshot",
                kind,
                identifier,
            )

        dynamic_path = self.cache_path(kind, identifier)
        self._validate_dynamic_boundary(dynamic_path)
        cached_path = _verified_file(
            self.dynamic_root, dynamic_path.relative_to(self.dynamic_root).as_posix()
        )
        if cached_path is not None and _is_valid_image(cached_path):
            return self._result(cached_path, "dynamic_cache", kind, identifier)

        if cached_path is not None:
            self._remove_invalid_cache(cached_path)
        if not url:
            return self._result(None, "none", kind, identifier)

        self._prepare_dynamic_target(dynamic_path)
        await self._download_to_target(url, dynamic_path, kind)
        downloaded_path = _verified_file(
            self.dynamic_root,
            dynamic_path.relative_to(self.dynamic_root).as_posix(),
        )
        if downloaded_path is None or not _is_valid_image(downloaded_path):
            raise AssetResolutionError(f"素材下载后不是可用图片: {kind}:{identifier}")
        return self._result(downloaded_path, "download", kind, identifier)

    @staticmethod
    def _result(
        path: Path | None,
        source: AssetSource,
        kind: str,
        identifier: str,
    ) -> ResolvedAsset:
        return ResolvedAsset(
            path=path,
            source=source,
            status="provided" if path is not None else "missing",
            incomplete=path is None,
            kind=kind,
            asset_id=identifier,
        )

    def _validate_dynamic_boundary(self, target: Path) -> None:
        """检查 L2 根、类型目录和目标文件的符号链接边界。"""

        if self.dynamic_root.is_symlink():
            raise AssetResolutionError("动态素材缓存根目录不能是符号链接")
        if self.dynamic_root.exists() and not self.dynamic_root.is_dir():
            raise AssetResolutionError("动态素材缓存根目录不是目录")
        try:
            relative = target.relative_to(self.dynamic_root)
        except ValueError as exc:
            raise AssetResolutionError("动态素材目标越出缓存根目录") from exc
        cursor = self.dynamic_root
        for part in relative.parts[:-1]:
            cursor /= part
            if cursor.is_symlink():
                raise AssetResolutionError("动态素材缓存目录不能是符号链接")
        if target.is_symlink():
            raise AssetResolutionError("动态素材缓存目标不能是符号链接")

    def _prepare_dynamic_target(self, target: Path) -> None:
        self._validate_dynamic_boundary(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._validate_dynamic_boundary(target)

    @staticmethod
    def _remove_invalid_cache(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise AssetResolutionError("损坏的动态素材缓存不是普通文件")
        try:
            path.unlink()
        except OSError as exc:
            raise AssetResolutionError("无法清理损坏的动态素材缓存") from exc

    async def _download_to_target(self, url: str, target: Path, kind: str) -> None:
        downloader = self.downloader
        if downloader is None:
            from ...utils.image_utils import download

            await download(url, target.parent, target.name, tag=f"[DNA-{kind}]")
            return

        fetch = getattr(downloader, "fetch", None)
        if callable(fetch):
            await fetch(url, target, tag=f"[DNA-{kind}]")
            return
        await downloader(url, target)  # type: ignore[operator]


__all__ = [
    "AssetDownloader",
    "AssetKind",
    "AssetResolutionError",
    "AssetResolver",
    "ResolvedAsset",
]
