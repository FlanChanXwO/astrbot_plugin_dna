"""原生配置管理器：替代 gsucore ``StringConfig``。

后端为 AstrBot 插件配置（``AstrBotConfig``，嵌套结构 ``{分组: {key: value}}``）。

- ``get_config("Key").data``：读取生效值（AstrBotConfig 有则用之，否则 schema 默认）。
- ``set_config("Key", value)``：写入并持久化。
- ``generate_astrbot_schema()``：生成 ``_conf_schema.json``（AstrBot WebUI 用）。
"""

from __future__ import annotations

from typing import Any

from .config_models import GSC


class ConfigItem:
    """``get_config`` 返回值：``.data`` 实时读取生效值。"""

    def __init__(self, manager: ConfigManager, key: str, schema: GSC) -> None:
        self._manager = manager
        self.key = key
        self.schema = schema

    @property
    def data(self) -> Any:
        return self._manager._get(self.key, self.schema.default)

    @property
    def default(self) -> Any:
        return self.schema.default

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def description(self) -> str:
        return self.schema.description

    @property
    def options(self) -> list | None:
        return self.schema.options

    @property
    def type(self) -> str:
        return self.schema._type


class ConfigManager:
    def __init__(
        self,
        name: str,
        config_schema: dict[str, GSC],
    ) -> None:
        self.name = name
        self.config_schema = config_schema
        self._config: dict[str, Any] | None = None

    # ---- AstrBotConfig 绑定 ----
    def bind(self, astrbot_config: dict[str, Any]) -> None:
        """绑定 AstrBot 插件配置字典（嵌套：``{name: {key: value}}``）。"""
        self._config = astrbot_config

    @property
    def is_bound(self) -> bool:
        return self._config is not None

    def _group(self) -> dict[str, Any]:
        if self._config is None:
            return {}
        group = self._config.get(self.name)
        return group if isinstance(group, dict) else {}

    # ---- 读 / 写 ----
    def _get(self, key: str, default: Any = None) -> Any:
        group = self._group()
        if key in group:
            return group[key]
        schema = self.config_schema.get(key)
        return schema.default if schema is not None else default

    def get_config(self, key: str) -> ConfigItem:
        schema = self.config_schema.get(key)
        if schema is None:
            raise KeyError(f"未知配置项: {key}")
        return ConfigItem(self, key, schema)

    def set_config(self, key: str, value: Any) -> None:
        if self._config is None:
            raise RuntimeError(f"ConfigManager {self.name} 尚未绑定 AstrBotConfig")
        group = self._config.setdefault(self.name, {})
        group[key] = value
        save = getattr(self._config, "save_config", None)
        if callable(save):
            save()

    def get_default_config(self) -> dict[str, Any]:
        return {k: v.default for k, v in self.config_schema.items()}

    # ---- _conf_schema.json 生成 ----
    def generate_astrbot_schema(self) -> dict[str, Any]:
        items: dict[str, Any] = {}
        for key, schema in self.config_schema.items():
            item: dict[str, Any] = {
                "type": schema._type,
                "description": schema.description,
                "default": schema.default,
            }
            if schema.options:
                item["options"] = schema.options
            if schema._type == "object":
                # AstrBot 解析 object 时始终读取 items；自由字典用空 schema 表示。
                item["items"] = {}
            items[key] = item
        return {
            self.name: {
                "description": self.name,
                "type": "object",
                "items": items,
            }
        }

    def get_config_path(self) -> str:
        return f"<AstrBotConfig>/plugin/{self.name}"


# ---- 全局 core 配置（HOST/PORT 等） ----
_core_config: dict[str, Any] | None = None


def bind_core_config(config: dict[str, Any]) -> None:
    """绑定 AstrBot 全局配置（main.py initialize 时调用）。"""
    global _core_config
    _core_config = config


def get_core_config(key: str, default: Any = None) -> Any:
    """读取 AstrBot 全局配置项（替代 gsucore ``core_config``）。"""
    if _core_config is None:
        return default
    return _core_config.get(key, default)
