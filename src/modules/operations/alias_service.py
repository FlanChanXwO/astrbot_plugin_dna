"""别名写入（添加/删除/恢复）use case。

写操作只修改运行期资源根下的 ``alias/{char,weapon}_alias.json``，按参数列表形式原子
写回；别名写入会改变 git 管理的资源文件，下一次 ``下载全部资源`` 的 ``pull --ff-only``
会因本地修改拒绝（安全边界）。离线测试使用隔离目录 fixture 验证。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...entry.response import PlainTextResponse
from . import messages


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class AliasService:
    """运行期别名 JSON 的添加/删除/恢复。"""

    def __init__(
        self,
        alias_root: str | Path,
        *,
        refresh: Callable[[], None] | None = None,
    ) -> None:
        self.alias_root = Path(alias_root)
        self.refresh = refresh or (lambda: None)

    def _path(self, alias_type: str | None) -> Path:
        is_weapon = alias_type == "武器"
        return self.alias_root / ("weapon_alias.json" if is_weapon else "char_alias.json")

    @staticmethod
    def _read(path: Path) -> dict[str, list[str]]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    async def add_delete_alias(self, request: object) -> PlainTextResponse:
        """按 action 添加/删除角色或武器别名。"""

        parameters = getattr(request, "parameters", {})
        action = str(parameters.get("action", "")).strip()
        alias_type = str(parameters.get("alias_type") or "").strip() or None
        name = str(parameters.get("name", "")).strip()
        new_alias = str(parameters.get("new_alias", "")).strip()
        if not name or not new_alias:
            return PlainTextResponse(messages.ALIAS_INPUT_EMPTY)
        path = self._path(alias_type)
        data = self._read(path)
        aliases = set(data.get(name, []))

        if action == "删除":
            if new_alias not in aliases:
                return PlainTextResponse(messages.ALIAS_NOT_FOUND.format(name=name, alias=new_alias))
            aliases.discard(new_alias)
            data[name] = sorted(aliases)
            if not aliases:
                data.pop(name, None)
            _atomic_write(path, data)
            self.refresh()
            return PlainTextResponse(messages.ALIAS_DELETED.format(name=name, alias=new_alias))

        if new_alias in aliases:
            return PlainTextResponse(messages.ALIAS_DUPLICATE.format(name=name, alias=new_alias))
        data[name] = sorted(aliases | {new_alias})
        _atomic_write(path, data)
        self.refresh()
        return PlainTextResponse(messages.ALIAS_ADDED.format(name=name, alias=new_alias))

    async def recover_alias(self, _request: object) -> PlainTextResponse:
        """恢复内置别名：重新加载运行期别名文件并刷新 catalog。"""

        self.refresh()
        return PlainTextResponse(messages.ALIAS_RECOVERED)


__all__ = ["AliasService"]
