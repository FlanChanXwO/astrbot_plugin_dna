"""别名写入（添加/删除/恢复）use case。

角色别名在配置了 ``custom_path`` 时写入运行期 custom 覆盖层，不修改公共资源仓库的
默认文件；未配置时默认使用 ``alias_root`` 的父目录下的 ``alias_custom.json``。
武器别名仍由原命令保留，角色 custom 层是 Goal 2 管理 API 的唯一写入边界。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...entry.response import PlainTextResponse
from ..admin.aliases import AdminAliasService
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
        custom_path: str | Path | None = None,
        refresh: Callable[[], None] | None = None,
    ) -> None:
        self.alias_root = Path(alias_root)
        self.refresh = refresh or (lambda: None)
        self.custom_path = (
            Path(custom_path)
            if custom_path is not None
            else self.alias_root.parent / "alias_custom.json"
        )
        self._admin_char_alias = AdminAliasService(
            self.alias_root / "char_alias.json",
            custom_path=self.custom_path,
            refresh=self.refresh,
        )

    def _path(self, alias_type: str | None) -> Path:
        is_weapon = alias_type == "武器"
        return self.alias_root / (
            "weapon_alias.json" if is_weapon else "char_alias.json"
        )

    async def _add_delete_custom_alias(
        self,
        action: str,
        name: str,
        new_alias: str,
    ) -> PlainTextResponse:
        """把角色命令转发给 custom 层并保持旧命令文案。"""

        service = self._admin_char_alias
        if service is None:
            raise RuntimeError("角色 custom alias service 未初始化")
        if action == "添加":
            result = await service.add_alias(name, new_alias)
        elif action == "删除":
            result = await service.delete_alias(name, new_alias)
        else:
            return PlainTextResponse("未知操作，仅支持「添加」或「删除」")
        if result.ok:
            if action == "添加":
                return PlainTextResponse(
                    messages.ALIAS_ADDED.format(name=name, alias=new_alias)
                )
            return PlainTextResponse(
                messages.ALIAS_DELETED.format(name=name, alias=new_alias)
            )
        error = result.error
        if error is None:
            return PlainTextResponse("别名保存失败")
        if error.code.value == "conflict":
            if action == "删除":
                return PlainTextResponse(f"别名【{new_alias}】为内置别名，无法删除")
            return PlainTextResponse(
                messages.ALIAS_DUPLICATE.format(name=name, alias=new_alias)
            )
        if error.code.value == "not_found":
            if action == "添加":
                return PlainTextResponse(f"角色【{name}】不存在，请检查名称")
            return PlainTextResponse(
                messages.ALIAS_NOT_FOUND.format(name=name, alias=new_alias)
            )
        return PlainTextResponse("别名保存失败")

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
        if alias_type != "武器":
            return await self._add_delete_custom_alias(action, name, new_alias)
        path = self._path(alias_type)
        data = self._read(path)
        aliases = set(data.get(name, []))

        if action == "删除":
            if new_alias not in aliases:
                return PlainTextResponse(
                    messages.ALIAS_NOT_FOUND.format(name=name, alias=new_alias)
                )
            aliases.discard(new_alias)
            data[name] = sorted(aliases)
            if not aliases:
                data.pop(name, None)
            _atomic_write(path, data)
            self.refresh()
            return PlainTextResponse(
                messages.ALIAS_DELETED.format(name=name, alias=new_alias)
            )

        if new_alias in aliases:
            return PlainTextResponse(
                messages.ALIAS_DUPLICATE.format(name=name, alias=new_alias)
            )
        data[name] = sorted(aliases | {new_alias})
        _atomic_write(path, data)
        self.refresh()
        return PlainTextResponse(
            messages.ALIAS_ADDED.format(name=name, alias=new_alias)
        )

    async def recover_alias(self, _request: object) -> PlainTextResponse:
        """恢复内置别名：重新加载运行期别名文件并刷新 catalog。"""

        result = await self._admin_char_alias.restore_all()
        if not result.ok:
            return PlainTextResponse("别名恢复失败")
        return PlainTextResponse(messages.ALIAS_RECOVERED)


__all__ = ["AliasService"]
