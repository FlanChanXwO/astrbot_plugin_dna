"""帮助卡片 HTML/T2I 渲染器。

展示分组、展示名、图标和排序全部来自 ``help_presentation`` 的
command id 显式映射；业务 registry 只负责确定当前调用者可见的命令集合。
静态资产经 StaticAssetResolver 解析，缓存连同资源完整性记录一起保存。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...version import PLUGIN_VERSION
from .assets import image_data_uri
from .help_presentation import (
    HELP_GROUP_DESCRIPTIONS,
    HELP_GROUP_ORDER,
    display_rank,
    get_presentation,
)
from .renderer import HtmlRenderer
from .spec import RenderSpec
from .static_assets import (
    StaticAssetResolver,
    static_font_data_uri,
    static_image_data_uri,
    static_record,
)

HELP_BACKGROUND_PATH = "textures/help/bg.jpg"
HELP_BANNER_PATH = "textures/help/banner_bg.jpg"
HELP_CAG_PATH = "textures/help/cag_bg.png"
HELP_ITEM_PATH = "textures/help/item.png"
HELP_FOOTER_PATH = "textures/common/footer.png"
HELP_FONT_PATH = "fonts/MiSansVF.woff2"
_PLUGIN_LOGO_PATH = Path(__file__).parents[3] / "logo.png"
_PLUGIN_LOGO_URI = image_data_uri(_PLUGIN_LOGO_PATH)

if TYPE_CHECKING:
    from ...entry.commands import CommandRegistry, PermissionName

CARD_W = 2020
HELP_TOP = 766
HELP_FOOTER_HEIGHT = 40
HELP_FOOTER_MARGIN_TOP = 32
HELP_FOOTER_MARGIN_BOTTOM = 40
_RENDERER = HtmlRenderer()

# Help 缓存必须连同资源完整性记录一起缓存，命中后才能恢复 incomplete 状态。
@dataclass(frozen=True)
class CachedHelp:
    payload: bytes
    resources: tuple[dict[str, str], ...]


_HELP_CACHE: dict[tuple[object, str, str, str, object], CachedHelp] = {}


def help_cache_generation_id(asset_resolver: object) -> object:
    """返回用于缓存键的稳定 generation 标识。

    不能使用 ``id(asset_resolver)``：对象地址可能被复用，导致重载后的新
    resolver 命中旧 generation 的缓存。有 generation 标识时用它；没有的
    resolver 退化到对象身份，仅作为同对象内的一致性键。
    """

    if asset_resolver is None:
        return None
    generation_id = getattr(asset_resolver, "generation_id", None)
    if isinstance(generation_id, str):
        return generation_id
    return ("identity", id(asset_resolver))


def invalidate_help_cache() -> None:
    """清除帮助卡缓存，使插件重载后不会复用旧 registry 或版本。"""

    _HELP_CACHE.clear()


def _format_example(eg: str, prefix: str = "dna") -> str:
    if not eg:
        return ""
    if not prefix:
        return eg
    parts = eg.split(" / ")
    formatted = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith(prefix):
            formatted.append(part)
        else:
            formatted.append(f"{prefix}{part}")
    return " / ".join(formatted)


def _with_unsubscribe_example(examples: list[str], description: str) -> list[str]:
    """为已实现双向订阅命令补出帮助卡中的取消订阅示例。"""

    if "订阅/取消订阅" not in description or any(
        example.startswith("取消订阅") for example in examples
    ):
        return examples
    for example in examples:
        if example.startswith("订阅"):
            return [*examples, f"取消{example}"]
    return examples


def _help_icon_uri(
    icon: str,
    asset_resolver: StaticAssetResolver | None,
    resource_records: list[dict[str, str]] | None = None,
) -> str:
    """按 presentation 显式声明的图标名从当前 resource generation 解析。"""

    key = f"texture.help.icon:{icon}"
    relative = f"textures/help/icon/{icon}"
    uri, asset = static_image_data_uri(asset_resolver, relative, label=icon)
    if resource_records is not None:
        resource_records.append(
            static_record(
                key,
                asset,
                resource_path=relative,
            ),
        )
    return uri


def _registry_help_sections(
    registry: CommandRegistry,
    permission: PermissionName,
    prefix: str,
    *,
    asset_resolver: StaticAssetResolver | None = None,
    resource_records: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """以 registry 为命令唯一来源、presentation 为展示事实源构造卡片数据。"""

    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    configured_prefixes = tuple(
        sorted(
            (prefix for prefix in registry.prefixes if prefix), key=len, reverse=True
        ),
    )
    for spec in registry.visible_specs(permission):
        presentation = get_presentation(spec.id)
        examples = []
        for example in spec.examples:
            for configured_prefix in configured_prefixes:
                if example.startswith(configured_prefix):
                    example = example[len(configured_prefix) :]
                    break
            examples.append(example)
        examples = _with_unsubscribe_example(examples, spec.description)
        item = {
            "example": _format_example(" / ".join(examples), prefix=prefix),
            "icon": _help_icon_uri(
                presentation.icon,
                asset_resolver,
                resource_records,
            ),
            "name": presentation.name,
        }
        grouped.setdefault(presentation.group, []).append(
            (display_rank(spec.id), item),
        )
    sections = [
        {
            "description": HELP_GROUP_DESCRIPTIONS.get(group, ""),
            "height": 140 + max(1, (len(items) + 3) // 4) * 175,
            "items": [item for _rank, item in sorted(items)],
            "name": group,
        }
        for group in _ordered_group_names(grouped)
        for items in (grouped[group],)
    ]
    return sections


def _ordered_group_names(grouped: dict[str, object]) -> list[str]:
    """按产品约定排序帮助分组，未知分组接在已知分组之后。"""

    preferred = {name: index for index, name in enumerate(HELP_GROUP_ORDER)}
    first_seen = {name: index for index, name in enumerate(grouped)}
    return sorted(
        grouped,
        key=lambda name: (preferred.get(name, len(preferred)), first_seen[name]),
    )


def _card_height(sections: list[dict[str, Any]]) -> int:
    """根据实际分组行数计算画布高度，给 footer 留出安全间距。"""

    content_bottom = HELP_TOP + sum(int(section["height"]) for section in sections)
    return (
        content_bottom
        + HELP_FOOTER_MARGIN_TOP
        + HELP_FOOTER_HEIGHT
        + HELP_FOOTER_MARGIN_BOTTOM
    )


async def get_help(
    prefix: str = "dna",
    *,
    registry: CommandRegistry,
    permission: PermissionName = "user",
    version: str = PLUGIN_VERSION,
    asset_resolver: StaticAssetResolver | None = None,
    resource_records: list[dict[str, str]] | None = None,
) -> bytes:
    """使用 HTML 模板绘制帮助卡片，按调用者权限展示普通/管理员分组。"""

    cache_key = (
        registry,
        prefix,
        permission,
        version,
        help_cache_generation_id(asset_resolver),
    )
    cached = _HELP_CACHE.get(cache_key)
    if cached is not None:
        if resource_records is not None:
            resource_records.extend(cached.resources)
        return cached.payload

    sections = _registry_help_sections(
        registry,
        permission,
        prefix,
        asset_resolver=asset_resolver,
        resource_records=resource_records,
    )
    def image_uri(key: str, relative: str, label: str) -> str:
        uri, asset = static_image_data_uri(asset_resolver, relative, label=label)
        if resource_records is not None:
            resource_records.append(
                static_record(key, asset, resource_path=relative),
            )
        return uri

    def font_uri_for(key: str, relative: str) -> str:
        uri, asset = static_font_data_uri(asset_resolver, relative)
        if resource_records is not None:
            resource_records.append(
                static_record(key, asset, resource_path=relative),
            )
        return uri

    background_uri = image_uri(
        "texture.help.background",
        HELP_BACKGROUND_PATH,
        "help-background",
    )
    banner_uri = image_uri("texture.help.banner", HELP_BANNER_PATH, "help-banner")
    cag_uri = image_uri("texture.help.cag", HELP_CAG_PATH, "help-cag")
    footer_uri = image_uri("texture.common.footer", HELP_FOOTER_PATH, "footer")
    item_uri = image_uri("texture.help.item", HELP_ITEM_PATH, "help-item")
    font_uri = font_uri_for("font.help", HELP_FONT_PATH)
    template_data = {
        "background": background_uri,
        "banner": banner_uri,
        "cag_background": cag_uri,
        "card_height": _card_height(sections),
        "font": font_uri,
        "footer": footer_uri,
        "icon": _PLUGIN_LOGO_URI,
        "item_background": item_uri,
        "lines": [],
        "sections": sections,
        "subtitle": "穿过寒夜，去往有你的春天。",
        "version": version,
        "width": CARD_W,
    }
    spec = RenderSpec(
        width=CARD_W,
        full_page=True,
        output_format="jpeg",
        quality=85,
    )
    payload = await _RENDERER.render("cards/help.html.j2", template_data, spec)
    _HELP_CACHE[cache_key] = CachedHelp(
        payload,
        tuple(resource_records) if resource_records is not None else (),
    )
    return payload


__all__ = ["get_help", "invalidate_help_cache"]
