"""运行期用户可见文案目录加载器。"""

from __future__ import annotations

import json
from pathlib import Path
from string import Formatter
from typing import Any


class I18nCatalogError(RuntimeError):
    """文案目录无法加载或校验失败。"""


class I18nKeyError(I18nCatalogError):
    """请求的文案 key 不存在。"""


class I18nTemplateError(I18nCatalogError):
    """文案模板格式错误或缺少参数。"""


class TipCatalog:
    """读取并严格校验嵌套 JSON 文案目录。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise I18nCatalogError(f"i18n 文案文件不存在: {self.path}")

        try:
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            raise I18nCatalogError(
                f"i18n 文案 JSON 损坏: {self.path}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise I18nCatalogError(f"i18n 文案文件无法读取: {self.path}") from exc

        if not isinstance(data, dict):
            raise I18nCatalogError(f"i18n 文案根节点必须是对象: {self.path}")
        self._validate_node(data, "")
        return data

    def _validate_node(self, value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise I18nCatalogError(
                        f"i18n 文案 key 必须是非空字符串: {self.path}"
                    )
                child_path = f"{path}.{key}" if path else key
                self._validate_node(child, child_path)
            return
        if not isinstance(value, str):
            raise I18nCatalogError(
                f"i18n 文案叶子节点必须是字符串: key={path!r}, file={self.path}"
            )
        if not value:
            raise I18nCatalogError(
                f"i18n 文案叶子节点不能为空: key={path!r}, file={self.path}"
            )
        try:
            list(Formatter().parse(value))
        except ValueError as exc:
            raise I18nTemplateError(
                f"i18n 文案模板格式错误: key={path!r}, file={self.path}"
            ) from exc

    def _template(self, key: str) -> str:
        if not key:
            raise I18nKeyError("i18n 文案 key 不能为空")

        value: Any = self._data
        for part in key.split("."):
            if not part or not isinstance(value, dict) or part not in value:
                raise I18nKeyError(
                    f"i18n 文案 key 不存在: key={key!r}, file={self.path}"
                )
            value = value[part]

        if not isinstance(value, str):
            raise I18nKeyError(
                f"i18n 文案 key 不是叶子节点: key={key!r}, file={self.path}"
            )
        return value

    def template(self, key: str) -> str:
        """读取已校验的模板原文，供兼容层保留 ``.format`` 调用形态。"""

        return self._template(key)

    def get(self, key: str, **params: object) -> str:
        """按点号路径读取文案，并严格执行模板格式化。"""

        value = self._template(key)
        try:
            result = value.format_map(params)
        except KeyError as exc:
            missing = exc.args[0]
            raise I18nTemplateError(
                f"i18n 文案模板缺少参数: key={key!r}, parameter={missing!r}"
            ) from exc
        except (IndexError, ValueError, AttributeError) as exc:
            raise I18nTemplateError(f"i18n 文案模板格式化失败: key={key!r}") from exc
        if not result:
            raise I18nTemplateError(f"i18n 文案格式化结果为空: key={key!r}")
        return result


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TIP_PATH = PLUGIN_ROOT / "i18" / "zh" / "tip.json"

_catalog: TipCatalog | None = None


def get_tip(key: str, **params: object) -> str:
    """读取插件默认中文运行期文案。"""

    global _catalog
    if _catalog is None:
        _catalog = TipCatalog(DEFAULT_TIP_PATH)
    return _catalog.get(key, **params)


def get_tip_template(key: str) -> str:
    """读取默认中文文案模板原文，仍经过目录加载期格式校验。"""

    global _catalog
    if _catalog is None:
        _catalog = TipCatalog(DEFAULT_TIP_PATH)
    return _catalog.template(key)


def validate_tip_catalog() -> None:
    """在插件加载阶段显式校验默认文案目录。"""

    global _catalog
    _catalog = TipCatalog(DEFAULT_TIP_PATH)


__all__ = [
    "DEFAULT_TIP_PATH",
    "I18nCatalogError",
    "I18nKeyError",
    "I18nTemplateError",
    "PLUGIN_ROOT",
    "TipCatalog",
    "get_tip",
    "get_tip_template",
    "validate_tip_catalog",
]
