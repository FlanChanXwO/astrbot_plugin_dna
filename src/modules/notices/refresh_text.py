"""密函刷新订阅通知的紧凑文本格式化。"""

from __future__ import annotations


def format_refresh_text(keys: list[str]) -> str:
    """将命中的密函键按类型聚合为一行通知文本。"""

    grouped: dict[str | None, list[str]] = {}
    for key in keys:
        type_name, separator, mh_name = key.partition(":")
        group_key = type_name if separator else None
        grouped.setdefault(group_key, []).append(mh_name or key)

    parts: list[str] = []
    for type_name, names in grouped.items():
        joined_names = "、".join(names)
        if type_name is None:
            parts.append(joined_names)
        else:
            parts.append(f"{type_name}「{joined_names}」")
    return "密函订阅已刷新：" + "；".join(parts)


__all__ = ["format_refresh_text"]
