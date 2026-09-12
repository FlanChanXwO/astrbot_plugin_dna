"""generation-first 的运行期图片素材解析。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast

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


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """一个素材请求的解析结果及其来源元数据。"""

    path: Path | None
    source: AssetSource
    status: AssetStatus
    incomplete: bool
    kind: str = ""
    asset_id: str = ""


@dataclass(frozen=True, slots=True)
class _AssetSpec:
    """一个逻辑素材类型在公共资源和动态缓存中的路径契约。"""

    snapshot_template: str
    cache_directory: str
    cache_filename: str


_ASSET_SPECS: dict[AssetKind, _AssetSpec] = {
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


def _normalize_kind(kind: AssetKind) -> AssetKind:
    normalized = str(kind).strip()
    if normalized not in _ASSET_SPECS:
        raise ValueError(f"不支持的图片素材类型: {kind!r}")
    return cast(AssetKind, normalized)


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
    ``optional_lease`` 内读取 L1。L1 始终只读，下载结果只写入 L2。
    """

    def __init__(
        self,
        *,
        dynamic_root: str | Path,
        snapshot_root: str | Path | None = None,
        coordinator: ResourceSnapshotCoordinator | None = None,
        downloader: AssetDownloader | None = None,
    ) -> None:
        self.dynamic_root = _absolute_path(dynamic_root)
        assert self.dynamic_root is not None
        self.snapshot_root = _absolute_path(snapshot_root)
        self.coordinator = coordinator
        self.downloader = downloader

    @classmethod
    def from_snapshot(
        cls,
        snapshot: object | None,
        *,
        dynamic_root: str | Path,
        downloader: AssetDownloader | None = None,
    ) -> AssetResolver:
        """从一个已持有的 generation snapshot 创建请求级 resolver。"""

        root = None if snapshot is None else getattr(snapshot, "root", None)
        return cls(
            snapshot_root=root,
            dynamic_root=dynamic_root,
            downloader=downloader,
        )

    def cache_path(self, kind: AssetKind, asset_id: str | int) -> Path:
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

    async def resolve(
        self,
        kind: AssetKind,
        asset_id: str | int,
        *,
        url: str | None = None,
    ) -> ResolvedAsset:
        """解析一个素材；本地双 miss 且有 URL 时才提交网络下载。"""

        normalized_kind = _normalize_kind(kind)
        identifier = _normalize_identifier(asset_id)
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

    async def _resolve_with_snapshot(
        self,
        snapshot_root: Path | None,
        kind: AssetKind,
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
        kind: AssetKind,
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

    async def _download_to_target(
        self,
        url: str,
        target: Path,
        kind: AssetKind,
    ) -> None:
        downloader = self.downloader
        if downloader is None:
            raise AssetResolutionError(
                f"素材网络下载需要 runtime AssetDownloader: {kind}:{target.name}"
            )
        await downloader.fetch(url, target, tag=f"[DNA-{kind}]")


__all__ = [
    "AssetDownloader",
    "AssetKind",
    "AssetResolutionError",
    "AssetResolver",
    "ResolvedAsset",
]
