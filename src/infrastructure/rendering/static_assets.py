"""静态资源解析器与无 resolver 兼容路径使用的本地资源常量。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from PIL import Image

from .assets import (
    AssetSource,
    pil_image_data_uri,
)
from .assets import (
    font_data_uri as _font_data_uri,
)
from .assets import (
    image_data_uri as _image_data_uri,
)
from .assets import (
    optimized_image_data_uri as _optimized_image_data_uri,
)
from .assets import (
    unicode_font_data_uris as _unicode_font_data_uris,
)
from .errors import AssetRenderError
from .runtime_assets import (
    placeholder_image,
    resolved_font_data_uri,
    resolved_image_data_uri,
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
        # 本地保留的通用装饰图目录；snapshot 缺失时作为 textures/common 的 fallback。
        self.bootstrap_texture_dir = (
            None if bootstrap_texture_dir is None else Path(bootstrap_texture_dir)
        )
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
        if self.coordinator is not None:
            snapshot = self.coordinator.current_snapshot
            self.snapshot_root = None if snapshot is None else snapshot.root
        relative = self.asset_paths.get(logical_key)
        if relative is None:
            return ResolvedStaticAsset(None, "none", True)
        safe = self._safe_relative(relative)
        if self.snapshot_root is not None:
            candidate = self.snapshot_root.joinpath(*safe.parts)
            if candidate.is_file() and not candidate.is_symlink():
                return ResolvedStaticAsset(candidate, "verified_snapshot", False)
        bootstrap = self.bootstrap_allowlist.get(logical_key)
        if bootstrap is not None and bootstrap.is_file() and not bootstrap.is_symlink():
            return ResolvedStaticAsset(bootstrap, "bootstrap", False)
        return ResolvedStaticAsset(None, "none", True)

    @property
    def generation_id(self) -> str | None:
        """当前解析器固定（或 coordinator 当前）的 generation 标识。"""

        if self._generation_id is not None:
            return self._generation_id
        snapshot = getattr(self.coordinator, "current_snapshot", None)
        return getattr(snapshot, "commit_sha", None)

    def resolve_relative(self, relative: str) -> ResolvedStaticAsset:
        """按 snapshot → 本地 bootstrap → missing 解析 snapshot 相对路径。"""

        safe = self._safe_relative(relative)
        snapshot_root = self.snapshot_root
        if snapshot_root is None and self.coordinator is not None:
            snapshot = self.coordinator.current_snapshot
            snapshot_root = None if snapshot is None else snapshot.root
        if snapshot_root is not None:
            candidate = snapshot_root.joinpath(*safe.parts)
            if candidate.is_file() and not candidate.is_symlink():
                return ResolvedStaticAsset(candidate, "verified_snapshot", False)
        if (
            self.bootstrap_texture_dir is not None
            and safe.parts[0] == "textures"
            and len(safe.parts) > 2
            and safe.parts[1] == "common"
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
        )._with_generation_id(generation_id or self.generation_id)

    def _with_generation_id(self, generation_id: str | None) -> StaticAssetResolver:
        self._generation_id = generation_id
        return self


RESOURCE_ROOT = Path(__file__).parents[2] / "resources"
RESOURCES_DIR = RESOURCE_ROOT

# 仅保留少量通用装饰图作为本地 bootstrap；完整纹理由 resource snapshot 提供。
BOOTSTRAP_TEXTURE_ROOT = Path(__file__).parents[2] / "utils" / "texture2d"
COMMON_PATH = BOOTSTRAP_TEXTURE_ROOT
DETAIL_TEXT_PATH = RESOURCE_ROOT / "textures" / "detail"
ROLE_TEXT_PATH = RESOURCE_ROOT / "textures" / "role"
STAMINA_TEXT_PATH = RESOURCE_ROOT / "textures" / "stamina"
WEEKLY_TEXT_PATH = RESOURCE_ROOT / "textures" / "weekly_report"
CALENDAR_TEXT_PATH = RESOURCE_ROOT / "textures" / "calendar"
TEXT_PATH = CALENDAR_TEXT_PATH
SIGN_TEXT_PATH = RESOURCE_ROOT / "textures" / "sign"
MH_TEXT_PATH = RESOURCE_ROOT / "textures" / "mh"
ANN_TEXT_PATH = RESOURCE_ROOT / "textures" / "ann"

BACKGROUND_PATH = COMMON_PATH / "bg1.jpg"
FONT_ORIGIN_PATH = RESOURCE_ROOT / "fonts" / "dna_fonts.ttf"
UNICODE_ORIGIN_PATH = RESOURCE_ROOT / "fonts" / "arial-unicode-ms-bold.ttf"
HELP_FONT_PATH = RESOURCE_ROOT / "fonts" / "MiSansVF.woff2"

HELP_DATA = RESOURCE_ROOT / "help" / "help.json"
HELP_DATA_FALLBACK = RESOURCE_ROOT / "help.json"
HELP_ICON_DIR = RESOURCE_ROOT / "help" / "icon_path"
HELP_BACKGROUND_PATH = RESOURCE_ROOT / "textures" / "help" / "bg.jpg"
HELP_BANNER_PATH = RESOURCE_ROOT / "textures" / "help" / "banner_bg.jpg"
HELP_CAG_PATH = RESOURCE_ROOT / "textures" / "help" / "cag_bg.png"
HELP_ITEM_PATH = RESOURCE_ROOT / "textures" / "help" / "item.png"
HELP_FOOTER_PATH = COMMON_PATH / "footer.png"
PLUGIN_ICON_PATH = Path(__file__).parents[3] / "logo.png"

OFFICIAL_AVATAR_PATH = ANN_TEXT_PATH / "dna_official_avatar.jpeg"


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
) -> Image.Image:
    """按 snapshot 相对路径读取 PIL 图片；缺失或损坏时返回占位图。"""

    asset = (
        resolver.resolve_relative(relative)
        if resolver is not None
        else ResolvedStaticAsset(None, "none", True)
    )
    if asset.path is not None:
        try:
            with Image.open(asset.path) as opened:
                image = opened.convert("RGBA")
            if image.size != size:
                image = image.resize(size, Image.Resampling.LANCZOS)
            return image
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    return placeholder_image(size, label)


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


def _legacy_label(source: AssetSource) -> str:
    return source.name if isinstance(source, Path) else "asset"


def legacy_image_data_uri(
    source: AssetSource,
    *,
    media_type: str | None = None,
) -> str:
    """读取旧 helper 的素材；素材已外置时返回可见 placeholder。"""

    try:
        return _image_data_uri(source, media_type=media_type)
    except (AssetRenderError, OSError, ValueError):
        legacy_path = source if isinstance(source, Path) else None
        return resolved_image_data_uri(
            None,
            f"legacy.image:{_legacy_label(source)}",
            legacy_path=legacy_path,
            label=_legacy_label(source),
        )[0]


def legacy_font_data_uri(
    source: AssetSource,
    *,
    media_type: str | None = None,
) -> str:
    """读取旧 helper 的字体；完整字体缺失时交给 CSS fallback。"""

    try:
        return _font_data_uri(source, media_type=media_type)
    except (AssetRenderError, OSError, ValueError):
        legacy_path = source if isinstance(source, Path) else None
        return resolved_font_data_uri(
            None,
            "legacy.font",
            legacy_path=legacy_path,
        )[0]


def legacy_optimized_image_data_uri(
    source: Path,
    *,
    size: tuple[int, int],
    crop: bool = False,
    image_format: str = "WEBP",
    quality: int = 85,
) -> str:
    """兼容旧尺寸优化 helper；外置素材未同步时返回尺寸稳定的 placeholder。"""

    try:
        return _optimized_image_data_uri(
            source,
            size=size,
            crop=crop,
            image_format=image_format,
            quality=quality,
        )
    except (AssetRenderError, OSError, ValueError):
        image = placeholder_image(size, _legacy_label(source))
        if image_format.upper() in {"JPEG", "JPG"}:
            image = image.convert("RGB")
        return pil_image_data_uri(image, image_format=image_format)


def legacy_unicode_font_data_uris(source: Path, text: str) -> tuple[str, str | None]:
    """兼容旧中文字体拆分 helper；字体外置时返回 CSS fallback。"""

    try:
        return _unicode_font_data_uris(source, text)
    except (AssetRenderError, OSError, ValueError):
        return legacy_font_data_uri(source), None


def open_legacy_image(
    source: Path,
    *,
    size: tuple[int, int],
    label: str,
) -> Image.Image:
    """旧 PIL helper 的安全读取边界，避免外置素材缺失阻断基础图片命令。"""

    try:
        with Image.open(source) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError):
        return placeholder_image(size, label)


__all__ = [
    "ANN_TEXT_PATH",
    "BACKGROUND_PATH",
    "CALENDAR_TEXT_PATH",
    "COMMON_PATH",
    "DETAIL_TEXT_PATH",
    "FONT_ORIGIN_PATH",
    "HELP_BACKGROUND_PATH",
    "HELP_BANNER_PATH",
    "HELP_CAG_PATH",
    "HELP_DATA",
    "HELP_DATA_FALLBACK",
    "HELP_FONT_PATH",
    "HELP_FOOTER_PATH",
    "HELP_ICON_DIR",
    "HELP_ITEM_PATH",
    "MH_TEXT_PATH",
    "OFFICIAL_AVATAR_PATH",
    "PLUGIN_ICON_PATH",
    "RESOURCES_DIR",
    "RESOURCE_ROOT",
    "ROLE_TEXT_PATH",
    "SIGN_TEXT_PATH",
    "STAMINA_TEXT_PATH",
    "TEXT_PATH",
    "UNICODE_ORIGIN_PATH",
    "WEEKLY_TEXT_PATH",
    "legacy_font_data_uri",
    "legacy_image_data_uri",
    "legacy_optimized_image_data_uri",
    "legacy_unicode_font_data_uris",
    "open_legacy_image",
    "static_font_data_uri",
    "static_image_data_uri",
    "static_open_image",
    "static_record",
]
