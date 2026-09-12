"""玩家卡图片解析、动态缓存与下载路由。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image

from ...utils.image import (
    _normalize_paint_img,
    get_attr_img,
    get_avatar_img,
    get_mod_img,
    get_paint_img,
    get_skill_img,
    get_weapon_attr_img,
    get_weapon_img,
)
from ..resources.resolver import ResolvedAsset


def _placeholder(size: tuple[int, int]) -> Image.Image:
    """返回一次渲染使用的内存占位图，不写入任何缓存。"""

    return Image.new("RGBA", size)


def _load_resolved_image(
    path: Path,
    placeholder_size: tuple[int, int],
) -> Image.Image | None:
    """读取 resolver 已验证的路径，并在解码失败时保留现有占位语义。"""

    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.convert("RGBA")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """一次图片解析的图像与 provenance 配对结果。"""

    image: Image.Image
    asset: ResolvedAsset


def _missing_asset(kind: str, asset_id: str | int) -> ResolvedAsset:
    """建立与透明占位图对应的缺失素材结果。"""

    return ResolvedAsset(
        path=None,
        source="none",
        status="missing",
        incomplete=True,
        kind=kind,
        asset_id=str(asset_id),
    )


async def _resolve_image(
    asset_resolver: Any,
    kind: str,
    asset_id: str | int,
    url: str | None,
    placeholder_size: tuple[int, int],
) -> PreparedImage:
    """从当前 generation/L2 解析一张可用于本次渲染的图片。"""

    try:
        resolved = await asset_resolver.resolve(
            kind,
            asset_id,
            url=url or None,
        )
    except (OSError, httpx.HTTPError, SyntaxError, ValueError):
        return PreparedImage(
            _placeholder(placeholder_size), _missing_asset(kind, asset_id)
        )
    if not isinstance(resolved, ResolvedAsset):
        raise TypeError("AssetResolver.resolve 必须返回 ResolvedAsset")
    asset = resolved
    if asset.path is None:
        return PreparedImage(_placeholder(placeholder_size), asset)
    image = _load_resolved_image(asset.path, placeholder_size)
    if image is None:
        return PreparedImage(
            _placeholder(placeholder_size), _missing_asset(kind, asset_id)
        )
    return PreparedImage(image, asset)


class PlayerImageLoader:
    """为玩家卡统一封装 L1/L2 图片解析与 legacy 动态素材入口。"""

    def __init__(self, asset_resolver: Any | None) -> None:
        self.asset_resolver = asset_resolver
        self._resolved_assets: dict[tuple[str, str], ResolvedAsset] = {}

    @property
    def resolved_assets(self) -> tuple[ResolvedAsset, ...]:
        """返回本次渲染实际解析过的素材结果。"""

        return tuple(
            self._resolved_assets[key] for key in sorted(self._resolved_assets)
        )

    def _remember(self, asset: ResolvedAsset) -> None:
        self._resolved_assets[(asset.kind, asset.asset_id)] = asset

    async def _resolved_image(
        self,
        kind: str,
        asset_id: str | int,
        url: str | None,
        placeholder_size: tuple[int, int],
    ) -> Image.Image:
        prepared = await _resolve_image(
            self.asset_resolver,
            kind,
            asset_id,
            url,
            placeholder_size,
        )
        self._remember(prepared.asset)
        return prepared.image

    @staticmethod
    def _cache_component(value: str | int) -> str:
        """校验动态素材标识并保留既有缓存文件名契约。"""

        component = str(value).strip()
        if (
            component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError("动态素材标识不能是路径段")
        return component

    def _validate_runtime_target(self, target: Path) -> None:
        """校验未纳入 AssetResolver 类型表的动态素材仍在 L2 根目录内。"""

        root = Path(self.asset_resolver.dynamic_root)
        if root.is_symlink():
            raise OSError("动态素材缓存根目录不能是符号链接")
        if root.exists() and not root.is_dir():
            raise OSError("动态素材缓存根目录不是目录")
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise OSError("动态素材目标越出缓存根目录") from exc
        cursor = root
        for part in relative.parts[:-1]:
            cursor /= part
            if cursor.is_symlink():
                raise OSError("动态素材缓存目录不能是符号链接")
        if target.is_symlink():
            raise OSError("动态素材缓存目标不能是符号链接")

    def _runtime_target(
        self,
        kind: str,
        asset_id: str | int,
        *,
        secondary_id: str | int | None = None,
    ) -> Path | None:
        root = getattr(self.asset_resolver, "dynamic_root", None)
        if root is None:
            return None
        root = Path(root)
        identifier = self._cache_component(asset_id)
        if kind == "skill":
            if secondary_id is None:
                raise ValueError("技能素材缺少角色 ID")
            return (
                root
                / "skill"
                / self._cache_component(secondary_id)
                / f"skill_{identifier}.png"
            )
        if kind == "user_avatar":
            return root / "user_avatar" / f"avatar_{identifier}.png"
        if kind == "mod":
            return root / "mod" / f"mod_{identifier}.png"
        if kind == "attr":
            return root / "attr" / f"attr_{identifier}.png"
        if kind == "weapon_attr":
            return root / "weapon_attr" / f"attr_{identifier}.png"
        raise ValueError(f"不支持的 runtime 图片素材类型: {kind!r}")

    async def _runtime_image(
        self,
        kind: str,
        asset_id: str | int,
        url: str | None,
        placeholder_size: tuple[int, int],
        *,
        secondary_id: str | int | None = None,
        optional: bool = False,
    ) -> Image.Image:
        target = self._runtime_target(
            kind,
            asset_id,
            secondary_id=secondary_id,
        )
        if target is None:
            asset = _missing_asset(kind, asset_id)
            self._remember(asset)
            return _placeholder(placeholder_size)

        self._validate_runtime_target(target)
        image = _load_resolved_image(target, placeholder_size)
        if image is not None:
            self._remember(
                ResolvedAsset(
                    path=target,
                    source="dynamic_cache",
                    status="provided",
                    incomplete=False,
                    kind=kind,
                    asset_id=str(asset_id),
                )
            )
            return image

        downloader = getattr(self.asset_resolver, "downloader", None)
        if not url or downloader is None:
            if optional:
                return _placeholder(placeholder_size)
            asset = _missing_asset(kind, asset_id)
            self._remember(asset)
            return _placeholder(placeholder_size)

        try:
            self._validate_runtime_target(target)
            fetch = getattr(downloader, "fetch", None)
            if callable(fetch):
                await fetch(url, target, tag=f"[DNA-{kind}]")
            else:
                await downloader(url, target)
            self._validate_runtime_target(target)
        except (OSError, httpx.HTTPError):
            if optional:
                return _placeholder(placeholder_size)
            asset = _missing_asset(kind, asset_id)
            self._remember(asset)
            return _placeholder(placeholder_size)

        image = _load_resolved_image(target, placeholder_size)
        if image is None:
            if optional:
                return _placeholder(placeholder_size)
            asset = _missing_asset(kind, asset_id)
            self._remember(asset)
            return _placeholder(placeholder_size)
        self._remember(
            ResolvedAsset(
                path=target,
                source="download",
                status="provided",
                incomplete=False,
                kind=kind,
                asset_id=str(asset_id),
            )
        )
        return image

    async def avatar(self, char_id: str | int, url: str | None) -> Image.Image:
        if self.asset_resolver is None:
            return await get_avatar_img(char_id, url)
        return await self._resolved_image(
            "role_avatar",
            char_id,
            url,
            (256, 256),
        )

    async def paint(self, char_id: str | int, url: str | None) -> Image.Image:
        if self.asset_resolver is None:
            return await get_paint_img(char_id, url)
        image = await self._resolved_image(
            "role_paint",
            char_id,
            url,
            (1320, 1320),
        )
        return _normalize_paint_img(image)

    async def weapon(self, weapon_id: str | int, url: str | None) -> Image.Image:
        if self.asset_resolver is None:
            return await get_weapon_img(weapon_id, url)
        image = await self._resolved_image(
            "weapon",
            weapon_id,
            url,
            (256, 256),
        )
        return image.resize((256, 256))

    async def mod(self, mod_id: str | int, url: str | None) -> Image.Image:
        if self.asset_resolver is None:
            return await get_mod_img(mod_id, url)
        return await self._runtime_image("mod", mod_id, url, (256, 256))

    async def skill(
        self,
        char_id: str | int,
        skill_name: str,
        url: str | None,
    ) -> Image.Image:
        if self.asset_resolver is None:
            return await get_skill_img(char_id, skill_name, url)
        return await self._runtime_image(
            "skill",
            skill_name.strip(),
            url,
            (128, 128),
            secondary_id=char_id,
        )

    async def attr(
        self,
        attr_id: str | int | None,
        url: str | None,
        *,
        optional: bool = False,
    ) -> Image.Image:
        if self.asset_resolver is None:
            return await get_attr_img(attr_id, url)
        identifier = attr_id
        if identifier is None:
            identifier = self._url_asset_id(url)
        return await self._runtime_image(
            "attr",
            identifier,
            url,
            (128, 128),
            optional=optional,
        )

    async def weapon_attr(
        self,
        attr_id: str | int | None,
        url: str | None,
        *,
        optional: bool = False,
    ) -> Image.Image:
        if self.asset_resolver is None:
            return await get_weapon_attr_img(attr_id, url)
        identifier = attr_id
        if identifier is None:
            identifier = self._url_asset_id(url)
        return await self._runtime_image(
            "weapon_attr",
            identifier,
            url,
            (128, 128),
            optional=optional,
        )

    async def user_avatar(self, user_id: str) -> Image.Image:
        if self.asset_resolver is None:
            raise RuntimeError("legacy loader 不负责 user avatar")
        url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        image = await self._runtime_image(
            "user_avatar",
            user_id,
            url,
            (640, 640),
        )
        asset_key = ("user_avatar", str(user_id))
        asset = self._resolved_assets.get(asset_key)
        if asset is not None and asset.incomplete:
            # 用户头像是资料头的可选增强；失败时沿用默认角色头像，并让最终
            # provenance 只描述实际绘入卡片的 fallback，避免一次头像失败阻断整卡缓存。
            self._resolved_assets.pop(asset_key, None)
            return await self.avatar("5101", None)
        return image

    @staticmethod
    def _url_asset_id(url: str | None) -> str:
        if not url:
            raise ValueError("素材 ID 和 URL 不能同时为空")
        parsed = urlsplit(url)
        if not parsed.path:
            raise ValueError("素材 URL 缺少路径")
        # URL basename 可能在不同目录、版本或 query 下重复；属性图没有稳定
        # upstream ID 时使用完整 URL 的稳定摘要，避免不同素材共用同一 L2 文件。
        return sha256(url.encode("utf-8")).hexdigest()


__all__ = ["PlayerImageLoader"]
