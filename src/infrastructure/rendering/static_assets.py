"""静态资源解析器与无 resolver 兼容路径使用的本地资源常量。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from PIL import Image

from .assets import (
    font_data_uri as _font_data_uri,
)
from .assets import (
    image_data_uri as _image_data_uri,
)
from .assets import pil_image_data_uri
from .errors import AssetRenderError
from .runtime_assets import (
    placeholder_image,
)

StaticAssetSource = Literal["verified_snapshot", "bootstrap", "none"]

if TYPE_CHECKING:
    from ..resources.generation import ResourceSnapshotCoordinator


@dataclass(frozen=True, slots=True)
class ResolvedStaticAsset:
    """静态资源解析结果；与动态图片 AssetResolver 完全隔离。"""

    path: Path | None
    source: StaticAssetSource
    incomplete: bool


class StaticAssetResolver:
    """按 verified generation → 显式 bootstrap → missing 解析静态资源。"""

    def __init__(
        self,
        *,
        snapshot_root: str | Path | None = None,
        coordinator: ResourceSnapshotCoordinator | None = None,
        bootstrap_allowlist: dict[str, str | Path] | None = None,
        asset_paths: dict[str, str] | None = None,
        bootstrap_texture_dir: str | Path | None = None,
        bootstrap_relative_allowlist: set[str] | None = None,
        bootstrap_dirs: dict[str, str | Path] | None = None,
    ) -> None:
        self.snapshot_root = (
            None if snapshot_root is None else Path(snapshot_root).resolve()
        )
        self.coordinator = coordinator
        self.bootstrap_allowlist = {
            key: Path(value).resolve()
            for key, value in (bootstrap_allowlist or {}).items()
        }
        self.asset_paths = dict(asset_paths or {})
        # 本地保留的通用装饰图目录；只有显式列入 allowlist 的相对路径才允许
        # 从这里回退，避免隐式 fallback 掩盖 dna-resource 的资源遗漏。
        self.bootstrap_texture_dir = (
            None if bootstrap_texture_dir is None else Path(bootstrap_texture_dir)
        )
        self.bootstrap_relative_allowlist = set(bootstrap_relative_allowlist or ())
        # 帮助图标等仅存在于插件包内的小型 UI 资源：key 前缀 → bootstrap 目录。
        self.bootstrap_dirs = {
            key: Path(value) for key, value in (bootstrap_dirs or {}).items()
        }
        # 已固定 generation 的副本会写入该字段；未固定时由 coordinator 推导。
        self._generation_id: str | None = None

    @staticmethod
    def _safe_relative(relative: str) -> PurePosixPath:
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"静态资源路径不安全: {relative!r}")
        return path

    def resolve(self, logical_key: str) -> ResolvedStaticAsset:
        """按 snapshot mapping → 显式 bootstrap mapping → missing 解析逻辑 key。

        bootstrap-only key（如 logo、帮助图标）没有 snapshot 映射，也必须能
        进入 bootstrap 检查。
        """

        if self.coordinator is not None:
            snapshot = self.coordinator.current_snapshot
            self.snapshot_root = None if snapshot is None else snapshot.root
        relative = self.asset_paths.get(logical_key)
        if relative is not None:
            safe = self._safe_relative(relative)
            if self.snapshot_root is not None:
                candidate = self.snapshot_root.joinpath(*safe.parts)
                if candidate.is_file() and not candidate.is_symlink():
                    return ResolvedStaticAsset(candidate, "verified_snapshot", False)
        bootstrap = self.bootstrap_allowlist.get(logical_key)
        if bootstrap is not None and bootstrap.is_file() and not bootstrap.is_symlink():
            return ResolvedStaticAsset(bootstrap, "bootstrap", False)
        # 帮助图标等 bootstrap 目录型 key：<prefix>:<filename>。
        if ":" in logical_key:
            prefix, filename = logical_key.split(":", 1)
            directory = self.bootstrap_dirs.get(prefix)
            if (
                directory is not None
                and not _safe_dir_member(filename)
                and (directory / filename).is_file()
            ):
                return ResolvedStaticAsset(directory / filename, "bootstrap", False)
        return ResolvedStaticAsset(None, "none", True)

    @property
    def generation_id(self) -> str | None:
        """当前解析器固定（或 coordinator 当前）的 generation 标识。"""

        if self._generation_id is not None:
            return self._generation_id
        snapshot = getattr(self.coordinator, "current_snapshot", None)
        return getattr(snapshot, "commit_sha", None)

    def resolve_relative(self, relative: str) -> ResolvedStaticAsset:
        """按 snapshot → 显式 bootstrap allowlist → missing 解析相对路径。"""

        safe = self._safe_relative(relative)
        snapshot_root = self.snapshot_root
        if snapshot_root is None and self.coordinator is not None:
            snapshot = self.coordinator.current_snapshot
            snapshot_root = None if snapshot is None else snapshot.root
        if snapshot_root is not None:
            candidate = snapshot_root.joinpath(*safe.parts)
            if candidate.is_file() and not candidate.is_symlink():
                return ResolvedStaticAsset(candidate, "verified_snapshot", False)
        # 仅显式列入 allowlist 的路径才允许回退本地 bootstrap 装饰图，
        # 防止 dna-resource 资源遗漏被本地同名文件静默掩盖。
        if (
            self.bootstrap_texture_dir is not None
            and str(PurePosixPath(relative)) in self.bootstrap_relative_allowlist
        ):
            candidate = self.bootstrap_texture_dir.joinpath(safe.parts[-1])
            if candidate.is_file() and not candidate.is_symlink():
                return ResolvedStaticAsset(candidate, "bootstrap", False)
        return ResolvedStaticAsset(None, "none", True)

    def pinned(
        self,
        snapshot_root: str | Path | None,
        *,
        generation_id: str | None = None,
    ) -> StaticAssetResolver:
        """返回固定在当前 generation 的请求级副本，杜绝一次渲染混用多个 generation。"""

        return StaticAssetResolver(
            snapshot_root=snapshot_root,
            coordinator=None,
            bootstrap_allowlist={
                key: str(value) for key, value in self.bootstrap_allowlist.items()
            },
            asset_paths=dict(self.asset_paths),
            bootstrap_texture_dir=self.bootstrap_texture_dir,
            bootstrap_relative_allowlist=set(self.bootstrap_relative_allowlist),
            bootstrap_dirs={
                key: str(value) for key, value in self.bootstrap_dirs.items()
            },
        )._with_generation_id(generation_id or self.generation_id)

    def listdir(self, relative: str) -> list[str]:
        """列出 snapshot 内某静态目录的文件名；目录不存在时返回空列表。"""

        safe = self._safe_relative(relative)
        snapshot_root = self.snapshot_root
        if snapshot_root is None and self.coordinator is not None:
            snapshot = self.coordinator.current_snapshot
            snapshot_root = None if snapshot is None else snapshot.root
        if snapshot_root is None:
            return []
        directory = snapshot_root.joinpath(*safe.parts)
        if not directory.is_dir():
            return []
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_file() and not entry.is_symlink()
        )

    def _with_generation_id(self, generation_id: str | None) -> StaticAssetResolver:
        self._generation_id = generation_id
        return self


def _safe_dir_member(filename: str) -> bool:
    """目录型 bootstrap key 的文件名安全检查。"""

    return (
        not filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    )


# 生产环境显式允许回退本地 bootstrap 的通用装饰图；其余静态资源缺失必须
# 暴露为 incomplete，避免本地同名文件掩盖 dna-resource 的资源遗漏。
BOOTSTRAP_RELATIVE_ALLOWLIST = {
    "textures/common/bg.jpg",
    "textures/common/bg1.jpg",
    "textures/common/bg2.jpg",
    "textures/common/div.png",
    "textures/common/footer.png",
    "textures/common/avatar_frame.png",
    "textures/common/avatar_title_bg.png",
    "textures/common/avatar_title_level.png",
    "textures/common/avatar_title_base_info.png",
}

RESOURCE_ROOT = Path(__file__).parents[2] / "resources"

# 仅保留少量通用装饰图与帮助素材作为本地 bootstrap；完整纹理由 resource snapshot 提供。
BOOTSTRAP_TEXTURE_ROOT = Path(__file__).parents[2] / "utils" / "texture2d"
COMMON_PATH = BOOTSTRAP_TEXTURE_ROOT

HELP_FONT_PATH = RESOURCE_ROOT / "fonts" / "MiSansVF.woff2"

HELP_ICON_DIR = RESOURCE_ROOT / "help" / "icon_path"
HELP_BACKGROUND_PATH = RESOURCE_ROOT / "textures" / "help" / "bg.jpg"
HELP_BANNER_PATH = RESOURCE_ROOT / "textures" / "help" / "banner_bg.jpg"
HELP_CAG_PATH = RESOURCE_ROOT / "textures" / "help" / "cag_bg.png"
HELP_ITEM_PATH = RESOURCE_ROOT / "textures" / "help" / "item.png"
HELP_FOOTER_PATH = COMMON_PATH / "footer.png"
PLUGIN_ICON_PATH = Path(__file__).parents[3] / "logo.png"


def static_image_data_uri(
    resolver: StaticAssetResolver | None,
    relative: str,
    *,
    label: str,
) -> tuple[str, ResolvedStaticAsset]:
    """解析 snapshot 相对路径的图片；缺失时返回可见 placeholder 并标记 incomplete。"""

    asset = (
        resolver.resolve_relative(relative)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    if asset.path is not None:
        try:
            return _image_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return (
        pil_image_data_uri(placeholder_image((96, 96), label)),
        ResolvedStaticAsset(None, "none", True),
    )


def static_font_data_uri(
    resolver: StaticAssetResolver | None,
    relative: str,
) -> tuple[str, ResolvedStaticAsset]:
    """解析 snapshot 相对路径的字体；缺失时返回空 URI 交给 CSS fallback。"""

    asset = (
        resolver.resolve_relative(relative)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    if asset.path is not None:
        try:
            return _font_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return "", ResolvedStaticAsset(None, "none", True)


def static_open_image(
    resolver: StaticAssetResolver | None,
    relative: str,
    *,
    size: tuple[int, int],
    label: str,
    resize: bool = True,
    key: str | None = None,
    records: list[dict[str, str]] | None = None,
) -> Image.Image:
    """按 snapshot 相对路径读取 PIL 图片；缺失或损坏时返回占位图。

    传入 ``key`` 与 ``records`` 时同步写入资源记录；先解码后记录，文件存在
    但损坏同样按 placeholder 记为 incomplete，不留静默降级。
    """

    asset = (
        resolver.resolve_relative(relative)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    image: Image.Image | None = None
    if asset.path is not None:
        try:
            with Image.open(asset.path) as opened:
                image = opened.convert("RGBA")
            if resize and image.size != size:
                image = image.resize(size, Image.Resampling.LANCZOS)
        except (OSError, ValueError, Image.DecompressionBombError):
            image = None
    if key is not None and records is not None:
        records.append(
            static_record(
                key,
                asset if image is not None else ResolvedStaticAsset(None, "none", True),
                resource_path=relative,
            )
        )
    if image is not None:
        return image
    return placeholder_image(size, label)


def static_key_image_data_uri(
    resolver: StaticAssetResolver | None,
    logical_key: str,
    *,
    label: str,
) -> tuple[str, ResolvedStaticAsset]:
    """按逻辑 key 解析图片；缺失时返回可见 placeholder 并标记 incomplete。"""

    asset = (
        resolver.resolve(logical_key)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    if asset.path is not None:
        try:
            return _image_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return (
        pil_image_data_uri(placeholder_image((96, 96), label)),
        ResolvedStaticAsset(None, "none", True),
    )


def static_key_font_data_uri(
    resolver: StaticAssetResolver | None,
    logical_key: str,
) -> tuple[str, ResolvedStaticAsset]:
    """按逻辑 key 解析字体；缺失时返回空 URI 交给 CSS fallback。"""

    asset = (
        resolver.resolve(logical_key)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    if asset.path is not None:
        try:
            return _font_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return "", ResolvedStaticAsset(None, "none", True)


def static_record(
    key: str,
    asset: ResolvedStaticAsset,
    *,
    resource_path: str = "",
) -> dict[str, str]:
    """把静态资源解析结果转换为 sidecar 资源记录。"""

    status = "provided" if asset.path is not None and not asset.incomplete else "fallback"
    return {
        "kind": "static",
        "key": key,
        "status": status,
        "source": asset.source,
        "incomplete": "true" if asset.incomplete else "false",
        "resource_path": resource_path,
    }



__all__ = [
    "BOOTSTRAP_RELATIVE_ALLOWLIST",
    "COMMON_PATH",
    "HELP_BACKGROUND_PATH",
    "HELP_BANNER_PATH",
    "HELP_CAG_PATH",
    "HELP_FONT_PATH",
    "HELP_FOOTER_PATH",
    "HELP_ICON_DIR",
    "HELP_ITEM_PATH",
    "PLUGIN_ICON_PATH",
    "static_font_data_uri",
    "static_image_data_uri",
    "static_open_image",
    "static_record",
]
