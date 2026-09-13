"""渲染器共用的运行期资源解析与降级工具。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

from ..resources.resolver import ResolvedAsset
from .assets import font_data_uri, image_data_uri, pil_image_data_uri
from .errors import AssetRenderError
from .fonts import load_runtime_font


class AssetResolverLike(Protocol):
    """渲染器只依赖的最小资源解析接口。"""

    def resolve(self, logical_key: str) -> ResolvedAsset:
        """按逻辑 key 返回当前 generation 的资源。"""


def resolve_runtime_asset(
    resolver: AssetResolverLike | None,
    logical_key: str,
    *,
    legacy_path: Path | None = None,
) -> ResolvedAsset:
    """解析资源；注入 resolver 后绝不回读插件目录中的 legacy 路径。"""

    if resolver is not None:
        return resolver.resolve(logical_key)
    if legacy_path is not None and legacy_path.is_file():
        return ResolvedAsset(
            path=legacy_path,
            source="bootstrap",
            status="provided",
            incomplete=False,
        )
    return ResolvedAsset(
        path=None,
        source="none",
        status="missing",
        incomplete=True,
    )


def resource_record(
    kind: str,
    key: str,
    asset: ResolvedAsset,
    *,
    resource_path: str = "",
) -> dict[str, str]:
    """把 resolver 结果转换为 sidecar 使用的稳定资源记录。"""

    if asset.path is None:
        status = "placeholder"
    elif asset.incomplete:
        status = "fallback"
    else:
        status = "provided"
    return {
        "kind": kind,
        "key": key,
        "status": status,
        "source": asset.source,
        "incomplete": "true" if asset.incomplete else "false",
        "resource_path": resource_path,
    }


def resources_incomplete(resources: Iterable[dict[str, str]]) -> bool:
    """判断一次渲染是否使用了 placeholder 或不完整 fallback。"""

    def is_incomplete(item: dict[str, str]) -> bool:
        # 新记录显式保存 incomplete；旧 renderer 只有 status 时，fallback/missing
        # 也必须按降级处理，避免图片已生成却被误写入完整缓存。
        explicit = item.get("incomplete")
        if explicit in {"true", "false"}:
            return explicit == "true"
        return item.get("status") in {"fallback", "missing", "placeholder"}

    return any(is_incomplete(item) for item in resources)


def placeholder_image(size: tuple[int, int], label: str) -> Image.Image:
    """生成稳定的小占位图，避免缺失资源时再次触碰文件系统。"""

    width, height = size
    image = Image.new("RGBA", (max(1, width), max(1, height)), (232, 236, 242, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(133, 145, 164, 255), width=2)
    draw.text((8, 8), label, fill=(74, 83, 99, 255), font=load_runtime_font(14))
    return image




def resolved_image_data_uri(
    resolver: AssetResolverLike | None,
    logical_key: str,
    *,
    legacy_path: Path | None = None,
    label: str,
) -> tuple[str, ResolvedAsset]:
    """返回模板图片 URI 及其解析结果。"""

    asset = resolve_runtime_asset(resolver, logical_key, legacy_path=legacy_path)
    if asset.path is not None:
        try:
            return image_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return pil_image_data_uri(placeholder_image((96, 96), label)), ResolvedAsset(
        path=None,
        source="placeholder",
        status="placeholder",
        incomplete=True,
    )


def resolved_font_data_uri(
    resolver: AssetResolverLike | None,
    logical_key: str,
    *,
    legacy_path: Path | None = None,
) -> tuple[str, ResolvedAsset]:
    """返回模板字体 URI；没有字体时以空 URI 交给 CSS fallback。"""

    asset = resolve_runtime_asset(resolver, logical_key, legacy_path=legacy_path)
    if asset.path is not None:
        try:
            return font_data_uri(asset.path), asset
        except (AssetRenderError, OSError, ValueError):
            pass
    return "", ResolvedAsset(
        path=None,
        source="placeholder",
        status="placeholder",
        incomplete=True,
    )


__all__ = [
    "AssetResolverLike",
    "placeholder_image",
    "resolve_runtime_asset",
    "resolved_font_data_uri",
    "resolved_image_data_uri",
    "resource_record",
    "resources_incomplete",
]
