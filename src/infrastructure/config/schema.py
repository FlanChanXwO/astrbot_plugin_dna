"""从 Pydantic 配置模型生成 AstrBot ``_conf_schema.json``。"""

from __future__ import annotations

import json
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr

from ...modules.client_updates.channels import CLIENT_UPDATE_CHANNELS
from .settings import (
    AISettings,
    CacheSettings,
    ClientUpdatesSettings,
    DisplaySettings,
    DnabySettings,
    GeneralSettings,
    LoginSettings,
    NetworkSettings,
    NotificationSettings,
    ResourceSettings,
    SignInSettings,
)

_GROUPS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("general", GeneralSettings),
    ("login", LoginSettings),
    ("ai", AISettings),
    ("sign_in", SignInSettings),
    ("notifications", NotificationSettings),
    ("client_updates", ClientUpdatesSettings),
    ("display", DisplaySettings),
    ("network", NetworkSettings),
    ("resources", ResourceSettings),
    ("cache", CacheSettings),
)

# AstrBot 会在插件构造函数之前按 schema 删除未知字段。这个字段不属于
# 新 typed model，只作为一次版本迁移窗口保留，确保旧 sign_in 配置能到达
# ``DnabySettings.from_config``。``invisible`` 防止它成为新的正式配置入口。
_SIGN_IN_COMPATIBILITY_FIELDS: dict[str, dict[str, Any]] = {
    "scheduled_enabled": {
        "type": "bool",
        "description": "旧版每日自动签到任务兼容开关",
        "hint": "仅用于升级旧配置；新配置请使用每个 UID 的自动签到选择",
        "default": True,
        "invisible": True,
    }
}


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

    result: dict[str, dict[str, Any]] = {}
    for group_name, model in _GROUPS:
        fields: dict[str, dict[str, Any]] = {}
        for field_name, field in model.model_fields.items():
            field_schema = _field_schema(field)
            if group_name == "client_updates" and field_name == "channels":
                field_schema["options"] = list(CLIENT_UPDATE_CHANNELS)
            fields[field_name] = field_schema
        if group_name == "sign_in":
            fields.update(
                {
                    field_name: dict(field_schema)
                    for field_name, field_schema in _SIGN_IN_COMPATIBILITY_FIELDS.items()
                }
            )
        result[group_name] = {
            "description": DnabySettings.model_fields[group_name].description
            or group_name,
            "type": "object",
            "items": fields,
        }
    return result


def write_astrbot_schema(path: str | Path) -> Path:
    """将代码生成的 schema 写入指定 JSON 文件并返回规范化路径。"""

    target = Path(path)
    target.write_text(
        json.dumps(generate_astrbot_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = ["generate_astrbot_schema", "write_astrbot_schema"]
