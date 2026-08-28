"""从 Pydantic 配置模型生成 AstrBot ``_conf_schema.json``。"""

from __future__ import annotations

import json
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr

from .settings import (
    DisplaySettings,
    DnabySettings,
    LoginSettings,
    NetworkSettings,
    NotificationSettings,
    ResourceSettings,
    SignInSettings,
)

_GROUPS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("login", LoginSettings),
    ("network", NetworkSettings),
    ("sign_in", SignInSettings),
    ("notifications", NotificationSettings),
    ("display", DisplaySettings),
    ("resources", ResourceSettings),
)


def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        non_none = [item for item in get_args(annotation) if item is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _literal_values(annotation: Any) -> list[Any] | None:
    annotation = _unwrap_optional(annotation)
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))

    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        args = get_args(annotation)
        if len(args) == 1:
            nested = _literal_values(args[0])
            if nested is not None:
                return nested
    return None


def _astrbot_type(annotation: Any) -> str:
    annotation = _unwrap_optional(annotation)
    if annotation is SecretStr or annotation is str:
        return "string"
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "int"
    if annotation is float:
        return "float"

    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        return "list"
    if origin is dict:
        return "object"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "object"
    return "string"


def _json_default(value: Any) -> Any:
    if isinstance(value, SecretStr):
        # schema 只提供可编辑的空默认值，避免未来误把密钥默认值写入仓库。
        return ""
    if isinstance(value, tuple):
        return [_json_default(item) for item in value]
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_default(item) for key, item in value.items()}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _field_schema(field: Any) -> dict[str, Any]:
    annotation = field.annotation
    item: dict[str, Any] = {
        "type": _astrbot_type(annotation),
        "description": field.description or "",
    }
    if field.json_schema_extra and isinstance(field.json_schema_extra, dict):
        for key in ("hint", "obvious_hint", "slider", "invisible"):
            if key in field.json_schema_extra:
                item[key] = field.json_schema_extra[key]

    item["default"] = _json_default(field.get_default(call_default_factory=True))
    options = _literal_values(annotation)
    if options is not None:
        item["options"] = [_json_default(option) for option in options]
    if item["type"] == "object":
        # AstrBot 对 object 节点始终递归读取 items；自由字典使用空 schema。
        item["items"] = {}
    return item


def generate_astrbot_schema() -> dict[str, dict[str, Any]]:
    """生成可被 AstrBot 4.27.x 递归解析的 schema。"""

    return {
        group_name: {
            "description": DnabySettings.model_fields[group_name].description
            or group_name,
            "type": "object",
            "items": {
                field_name: _field_schema(field)
                for field_name, field in model.model_fields.items()
            },
        }
        for group_name, model in _GROUPS
    }


def write_astrbot_schema(path: str | Path) -> Path:
    """将代码生成的 schema 写入指定 JSON 文件并返回规范化路径。"""

    target = Path(path)
    target.write_text(
        json.dumps(generate_astrbot_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = ["generate_astrbot_schema", "write_astrbot_schema"]
