"""原生配置模型：替代 gsucore ``GsCore.utils.plugins_config.models``。

每个 ``Gs*Config`` 声明一项配置的 schema（name/description/data 默认值/options）。
实际生效值由 ``ConfigManager`` 从 ``AstrBotConfig`` 读取；这里只保留定义与 ``.data`` 默认值。

构造签名与 gsucore 一致：``(name, description, data=default, options=...)``。
"""

from __future__ import annotations

from typing import Any


class GSC:
    _type: str = "string"

    def __init__(
        self,
        name: str,
        description: str,
        data: Any = None,
        options: list | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self._data = data
        self.options = options

    @property
    def data(self) -> Any:
        return self._data

    @property
    def default(self) -> Any:
        return self._data


class GsIntConfig(GSC):
    _type = "int"

    def __init__(
        self,
        name: str,
        description: str,
        data: int = 0,
        max_value: int | None = None,
    ) -> None:
        super().__init__(name, description, data)
        self.max_value = max_value


class GsStrConfig(GSC):
    _type = "string"


class GsBoolConfig(GSC):
    _type = "bool"


class GsDictConfig(GSC):
    _type = "object"


class GsListConfig(GSC):
    _type = "list"


class GsListStrConfig(GsListConfig):
    _type = "list"


class GsTimeConfig(GSC):
    _type = "string"


class GsTimeRConfig(GSC):
    _type = "string"
