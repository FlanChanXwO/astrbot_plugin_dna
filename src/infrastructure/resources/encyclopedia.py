"""百科图片、攻略和别名的运行期资源读取。

资源根目录由 bootstrap 从 ``StarTools.get_data_dir`` 派生；本模块不向插件源码
目录写入文件，也不在缺失素材时联网下载。测试可以注入已存在的 Path fixture。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class EncyclopediaResourceError(ValueError):
    """资源目录或 JSON 内容不符合资料模块契约。"""


@dataclass(frozen=True, slots=True)
class GuideAsset:
    """一个攻略作者提供的图片。"""

    provider: str
    path: Path


@dataclass(frozen=True, slots=True)
class AliasCatalog:
    """角色/武器别名的只读合并视图。"""

    char_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    weapon_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "char_aliases", self._normalize(self.char_aliases))
        object.__setattr__(self, "weapon_aliases", self._normalize(self.weapon_aliases))

    @staticmethod
    def _normalize(data: Mapping[str, tuple[str, ...] | list[str]]) -> dict[str, tuple[str, ...]]:
        return {
            str(name): tuple(str(alias) for alias in aliases)
            for name, aliases in data.items()
        }

    @staticmethod
    def _resolve(data: Mapping[str, tuple[str, ...]], name: str) -> str | None:
        normalized = name.strip()
        if not normalized:
            return None
        for canonical, aliases in data.items():
            if normalized == canonical or normalized in aliases:
                return canonical
        # 保留 legacy 的包含匹配，便于“角色甲”与带后缀的资源别名兼容；
        # 仅在已加载的只读 catalog 内匹配，不接受任意路径或模糊网络查询。
        for canonical, aliases in data.items():
            if normalized in canonical or any(normalized in alias for alias in aliases):
                return canonical
        return None

    def resolve_char(self, name: str) -> str | None:
        """将角色别名解析为 canonical name。"""

        return self._resolve(self.char_aliases, name)

    def resolve_weapon(self, name: str) -> str | None:
        """将武器别名解析为 canonical name。"""

        return self._resolve(self.weapon_aliases, name)

    def char_alias_list(self, name: str) -> tuple[str, ...] | None:
        canonical = self.resolve_char(name)
        return None if canonical is None else self.char_aliases[canonical]

    def weapon_alias_list(self, name: str) -> tuple[str, ...] | None:
        canonical = self.resolve_weapon(name)
        return None if canonical is None else self.weapon_aliases[canonical]

    def all_chars(self) -> tuple[str, ...]:
        return tuple(self.char_aliases)

    def all_weapons(self) -> tuple[str, ...]:
        return tuple(self.weapon_aliases)


@dataclass(frozen=True, slots=True)
class EncyclopediaResourceStore:
    """资料资源的只读索引。"""

    aliases: AliasCatalog = field(default_factory=AliasCatalog)
    wiki_assets: Mapping[tuple[str, str], Path] = field(default_factory=dict)
    guide_assets: Mapping[str, tuple[GuideAsset, ...]] = field(default_factory=dict)
    weekly_assets: Mapping[int, Path] = field(default_factory=dict)
    calendar_assets: Mapping[str, Path] = field(default_factory=dict)
    font_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "wiki_assets",
            {
                (str(kind), str(name)): Path(path)
                for (kind, name), path in self.wiki_assets.items()
            },
        )
        object.__setattr__(
            self,
            "guide_assets",
            {
                str(name): tuple(assets)
                for name, assets in self.guide_assets.items()
            },
        )
        object.__setattr__(
            self,
            "weekly_assets",
            {int(item_id): Path(path) for item_id, path in self.weekly_assets.items()},
        )
        object.__setattr__(
            self,
            "calendar_assets",
            {str(name): Path(path) for name, path in self.calendar_assets.items()},
        )
        if self.font_path is not None:
            object.__setattr__(self, "font_path", Path(self.font_path))

    @staticmethod
    def _read_alias_file(path: Path) -> dict[str, tuple[str, ...]]:
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EncyclopediaResourceError(f"别名资源不可读: {path.name}") from error
        if not isinstance(raw, dict):
            raise EncyclopediaResourceError(f"别名资源格式错误: {path.name}")
        result: dict[str, tuple[str, ...]] = {}
        for name, aliases in raw.items():
            if not isinstance(name, str) or not isinstance(aliases, list):
                raise EncyclopediaResourceError(f"别名资源条目格式错误: {path.name}")
            result[name] = tuple(str(alias) for alias in aliases)
        return result

    @classmethod
    def from_root(cls, root: str | Path) -> EncyclopediaResourceStore:
        """从运行期资源根读取 alias/wiki/guide 索引，不创建或覆盖任何文件。"""

        root_path = Path(root).expanduser().resolve()
        alias_root = root_path / "alias"
        aliases = AliasCatalog(
            char_aliases=cls._read_alias_file(alias_root / "char_alias.json"),
            weapon_aliases=cls._read_alias_file(alias_root / "weapon_alias.json"),
        )

        wiki_assets: dict[tuple[str, str], Path] = {}
        for kind in ("role", "weapon", "spirit"):
            kind_root = root_path / "wiki" / kind
            if not kind_root.is_dir():
                continue
            for path in sorted(kind_root.iterdir()):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    wiki_assets[(kind, path.stem)] = path

        weekly_assets: dict[int, Path] = {}
        weekly_root = root_path / "weekly_item"
        if weekly_root.is_dir():
            for path in sorted(weekly_root.iterdir()):
                if not path.is_file():
                    continue
                try:
                    item_id = int(path.stem.removeprefix("item_"))
                except ValueError:
                    continue
                weekly_assets[item_id] = path

        calendar_assets: dict[str, Path] = {}
        calendar_root = root_path / "calendar"
        if calendar_root.is_dir():
            for path in sorted(calendar_root.iterdir()):
                if path.is_file():
                    calendar_assets[path.name] = path
                    calendar_assets[path.stem] = path

        guides: dict[str, list[GuideAsset]] = {}
        guide_root = root_path / "guide"
        for provider_root in sorted(guide_root.iterdir()) if guide_root.is_dir() else ():
            if not provider_root.is_dir():
                continue
            provider = provider_root.name
            for path in sorted(provider_root.iterdir()):
                if not path.is_file():
                    continue
                filename = path.name.casefold()
                for canonical in aliases.char_aliases:
                    if canonical.casefold() in filename:
                        guides.setdefault(canonical, []).append(GuideAsset(provider, path))

        return cls(
            aliases=aliases,
            wiki_assets=wiki_assets,
            guide_assets={name: tuple(items) for name, items in guides.items()},
            weekly_assets=weekly_assets,
            calendar_assets=calendar_assets,
            font_path=(root_path / "fonts" / "dna_fonts.ttf")
            if (root_path / "fonts" / "dna_fonts.ttf").is_file()
            else None,
        )

    @property
    def font_status(self) -> str:
        """暴露字体资源状态，供 renderer 记录资源差异。"""

        return "provided" if self.font_path is not None and self.font_path.is_file() else "fallback"

    def wiki_asset(self, name: str) -> tuple[str, Path] | None:
        """按角色、武器、魔灵顺序返回已存在的图鉴素材。"""

        canonical = self.aliases.resolve_char(name)
        if canonical is not None:
            path = self.wiki_assets.get(("role", canonical))
            if path is not None and path.is_file():
                return "role", path

        canonical = self.aliases.resolve_weapon(name)
        if canonical is not None:
            path = self.wiki_assets.get(("weapon", canonical))
            if path is not None and path.is_file():
                return "weapon", path

        for (kind, canonical_name), path in self.wiki_assets.items():
            if kind == "spirit" and canonical_name == name.strip() and path.is_file():
                return "spirit", path
        return None

    def weekly_asset(self, item_id: int) -> Path | None:
        """返回已存在的周报资源图标。"""

        path = self.weekly_assets.get(item_id)
        return path if path is not None and path.is_file() else None

    def calendar_asset(self, pic: str) -> Path | None:
        """按本地文件名返回日历素材；URL 不在资源层下载。"""

        normalized = Path(pic).name if pic else ""
        path = self.calendar_assets.get(pic) or self.calendar_assets.get(normalized)
        return path if path is not None and path.is_file() else None

    def guides_for(self, name: str, providers: tuple[str, ...]) -> tuple[GuideAsset, ...]:
        """解析角色并按配置选择攻略作者，保持资源索引顺序。"""

        canonical = self.aliases.resolve_char(name)
        if canonical is None:
            return ()
        assets = tuple(
            asset
            for asset in self.guide_assets.get(canonical, ())
            if asset.path.is_file() and ("all" in providers or asset.provider in providers)
        )
        return assets


__all__ = [
    "AliasCatalog",
    "EncyclopediaResourceError",
    "EncyclopediaResourceStore",
    "GuideAsset",
]
