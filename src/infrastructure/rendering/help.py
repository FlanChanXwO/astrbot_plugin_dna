"""帮助卡片 HTML/T2I 渲染器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...entry.commands import COMMAND_GROUP_ORDER
from ...version import PLUGIN_VERSION
from .assets import font_data_uri, image_data_uri
from .renderer import HtmlRenderer
from .spec import RenderSpec

if TYPE_CHECKING:
    from ...entry.commands import CommandRegistry, PermissionName

HELP_DATA = Path(__file__).parents[2] / "resources" / "help" / "help.json"
BACKGROUND_PATH = (
    Path(__file__).parents[2] / "resources" / "textures" / "help" / "bg.jpg"
)
HELP_FONT_PATH = Path(__file__).parents[2] / "resources" / "fonts" / "MiSansVF.woff2"
ICON_DIR = Path(__file__).parents[2] / "resources" / "help" / "icon_path"

CARD_W = 2020
HELP_TOP = 766
HELP_FOOTER_HEIGHT = 40
HELP_FOOTER_MARGIN_TOP = 32
HELP_FOOTER_MARGIN_BOTTOM = 40
_RENDERER = HtmlRenderer()
_ICON_ALIASES = {
    # GScore 依赖目录遍历顺序处理部分命中；显式固定两个无同名文件的歧义项。
    "基本信息卡片": "基本信息.png",
    "查看UID列表": "UID.png",
}
_HELP_CACHE: dict[tuple[object, str, str, str], bytes] = {}


def invalidate_help_cache() -> None:
    """清除帮助卡缓存，使插件重载后不会复用旧 registry 或版本。"""

    _HELP_CACHE.clear()


def _load_help_data() -> dict[str, Any]:
    if not HELP_DATA.exists():
        fallback = Path(__file__).parents[2] / "resources" / "help.json"
        if fallback.exists():
            with fallback.open("r", encoding="utf-8") as file:
                return json.load(file)
    with HELP_DATA.open("r", encoding="utf-8") as file:
        return json.load(file)


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


def _help_display_name(command_id: str, name: str) -> str:
    """避免把密函推送时间窗口设置误解成独立订阅。"""

    if command_id == "mh_subscribe_cycle":
        return "设置密函推送时间"
    return name


def _iter_help_lines(plugin_help: dict[str, Any], prefix: str = "dna"):
    """生成保持旧分组和示例语义的帮助条目 payload。"""
    for group_name, group_data in plugin_help.items():
        yield {"is_group": True, "name": group_name, "example": ""}
        for item in group_data.get("data", []):
            yield {
                "is_group": False,
                "name": item.get("name", ""),
                "example": _format_example(item.get("eg", ""), prefix=prefix),
            }


def _find_icon(name: str) -> Path:
    icon_dir = ICON_DIR
    if alias := _ICON_ALIASES.get(name):
        return icon_dir / alias
    exact = icon_dir / f"{name}.png"
    if exact.exists():
        return exact
    for path in icon_dir.glob("*.png"):
        if path.stem in name:
            return path
    return icon_dir / "通用.png"


def _help_sections(
    plugin_help: dict[str, Any], prefix: str = "dna"
) -> list[dict[str, Any]]:
    """按 GScore new_help 的分组、列数和条目顺序构造模板数据。"""
    sections: list[dict[str, Any]] = []
    for name in _ordered_group_names(plugin_help):
        value = plugin_help[name]
        items = []
        for command in value.get("data", []):
            item_name = str(command.get("name", ""))
            items.append(
                {
                    "example": _format_example(
                        str(command.get("eg", "")), prefix=prefix
                    ),
                    "icon": image_data_uri(_find_icon(item_name)),
                    "name": item_name,
                }
            )
        rows = max(1, (len(items) + 3) // 4)
        sections.append(
            {
                "description": str(value.get("desc", "")),
                "height": 140 + rows * 175,
                "items": items,
                "name": name,
            },
        )
    return sections


def _registry_help_sections(
    registry: CommandRegistry,
    permission: PermissionName,
    prefix: str,
    plugin_help: dict[str, Any],
) -> list[dict[str, Any]]:
    """以 registry 为命令唯一来源，同时沿用资源文件中的分组说明和图标。"""

    descriptions = {
        name: str(value.get("desc", ""))
        for name, value in plugin_help.items()
        if isinstance(value, dict)
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    configured_prefixes = tuple(
        sorted(
            (prefix for prefix in registry.prefixes if prefix), key=len, reverse=True
        ),
    )
    for spec in registry.visible_specs(permission):
        examples = []
        for example in spec.examples:
            for configured_prefix in configured_prefixes:
                if example.startswith(configured_prefix):
                    example = example[len(configured_prefix) :]
                    break
            examples.append(example)
        examples = _with_unsubscribe_example(examples, spec.description)
        grouped.setdefault(spec.group, []).append(
            {
                "example": _format_example(" / ".join(examples), prefix=prefix),
                "icon": image_data_uri(_find_icon(spec.name)),
                "name": _help_display_name(spec.id, spec.name),
            },
        )
    sections = [
        {
            "description": descriptions.get(group, ""),
            "height": 140 + max(1, (len(items) + 3) // 4) * 175,
            "items": items,
            "name": group,
        }
        for group in _ordered_group_names(grouped)
        for items in (grouped[group],)
    ]
    return sections


def _ordered_group_names(grouped: dict[str, object]) -> list[str]:
    """按产品约定排序帮助分组，未知分组接在已知分组之后。"""

    preferred = {name: index for index, name in enumerate(COMMAND_GROUP_ORDER)}
    first_seen = {name: index for index, name in enumerate(grouped)}
    return sorted(
        grouped,
        key=lambda name: (preferred.get(name, len(preferred)), first_seen[name]),
    )


def _card_height(sections: list[dict[str, Any]], lines: list[dict[str, Any]]) -> int:
    """根据实际分组行数计算画布高度，给 footer 留出安全间距。"""

    if sections:
        content_bottom = HELP_TOP + sum(int(section["height"]) for section in sections)
    else:
        rows = max(1, (len(lines) + 3) // 4)
        content_bottom = 900 + rows * 175
    return (
        content_bottom
        + HELP_FOOTER_MARGIN_TOP
        + HELP_FOOTER_HEIGHT
        + HELP_FOOTER_MARGIN_BOTTOM
    )


async def get_help(
    prefix: str = "dna",
    *,
    registry: CommandRegistry | None = None,
    permission: PermissionName = "user",
    version: str = PLUGIN_VERSION,
) -> bytes:
    """使用 HTML 模板绘制帮助卡片，保留双列与三列排版结构。"""

    cache_key = (
        (registry, prefix, permission, version) if registry is not None else None
    )
    if cache_key is not None and cache_key in _HELP_CACHE:
        return _HELP_CACHE[cache_key]

    plugin_help = _load_help_data()
    if registry is None:
        sections = _help_sections(plugin_help, prefix=prefix)
        lines = list(_iter_help_lines(plugin_help, prefix=prefix))
    else:
        sections = _registry_help_sections(registry, permission, prefix, plugin_help)
        lines = []
    template_data = {
        "background": image_data_uri(BACKGROUND_PATH),
        "banner": image_data_uri(
            Path(__file__).parents[2]
            / "resources"
            / "textures"
            / "help"
            / "banner_bg.jpg",
        ),
        "cag_background": image_data_uri(
            Path(__file__).parents[2]
            / "resources"
            / "textures"
            / "help"
            / "cag_bg.png",
        ),
        "card_height": _card_height(sections, lines),
        "font": font_data_uri(HELP_FONT_PATH),
        "footer": image_data_uri(
            Path(__file__).parents[2]
            / "resources"
            / "textures"
            / "common"
            / "footer.png",
        ),
        "icon": image_data_uri(Path(__file__).parents[3] / "logo.png"),
        "item_background": image_data_uri(
            Path(__file__).parents[2] / "resources" / "textures" / "help" / "item.png",
        ),
        "lines": lines,
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
    if cache_key is not None:
        _HELP_CACHE[cache_key] = payload
    return payload


__all__ = ["get_help", "invalidate_help_cache"]
