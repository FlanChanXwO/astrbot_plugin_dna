"""角色默认别名与运行期 custom 覆盖层的 Admin API。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import AdminApiResponse, AdminError, AdminErrorCode


class AliasStorageError(ValueError):
    """默认或 custom 别名文件不可读或格式不符合契约。"""


def _failure(code: AdminErrorCode, message: str) -> AdminApiResponse[Any]:
    """建立不携带文件路径或底层异常的失败响应。"""

    return AdminApiResponse.failure(AdminError(code, message))


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _alias_key(value: str) -> str:
    return value.casefold()


@dataclass(frozen=True, slots=True)
class AdminAliasEntry:
    """一个角色的默认、自定义和有效别名视图。"""

    canonical_name: str
    default_aliases: tuple[str, ...]
    custom_aliases: tuple[str, ...]
    effective_aliases: tuple[str, ...]

    @property
    def name(self) -> str:
        """canonical name 的 API 友好别名。"""

        return self.canonical_name

    @property
    def defaults(self) -> tuple[str, ...]:
        return self.default_aliases

    @property
    def custom(self) -> tuple[str, ...]:
        return self.custom_aliases

    @property
    def effective(self) -> tuple[str, ...]:
        return self.effective_aliases

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "default_aliases": list(self.default_aliases),
            "custom_aliases": list(self.custom_aliases),
            "effective_aliases": list(self.effective_aliases),
        }


@dataclass(frozen=True, slots=True)
class AdminAliasCatalog:
    """全部角色和武器的默认 + custom 别名目录。"""

    entries: tuple[AdminAliasEntry, ...]
    weapon_entries: tuple[AdminAliasEntry, ...] = ()

    @property
    def roles(self) -> tuple[AdminAliasEntry, ...]:
        return self.entries

    @property
    def characters(self) -> tuple[AdminAliasEntry, ...]:
        return self.entries

    @property
    def weapons(self) -> tuple[AdminAliasEntry, ...]:
        return self.weapon_entries

    def role(self, canonical_name: str) -> AdminAliasEntry | None:
        normalized = _normalized_text(canonical_name)
        if normalized is None:
            return None
        for entry in self.entries:
            if entry.canonical_name == normalized:
                return entry
        return None

    def weapon(self, canonical_name: str) -> AdminAliasEntry | None:
        normalized = _normalized_text(canonical_name)
        if normalized is None:
            return None
        for entry in self.weapon_entries:
            if entry.canonical_name == normalized:
                return entry
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "roles": [entry.to_dict() for entry in self.entries],
            "weapons": [entry.to_dict() for entry in self.weapon_entries],
        }


def _read_alias_mapping(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AliasStorageError from error
    if not isinstance(raw, dict):
        raise AliasStorageError
    result: dict[str, list[str]] = {}
    for raw_name, raw_aliases in raw.items():
        name = _normalized_text(raw_name)
        if name is None or not isinstance(raw_aliases, list):
            raise AliasStorageError
        aliases: list[str] = []
        seen: set[str] = set()
        for raw_alias in raw_aliases:
            alias = _normalized_text(raw_alias)
            if alias is None:
                raise AliasStorageError
            key = _alias_key(alias)
            if key in seen:
                raise AliasStorageError
            seen.add(key)
            aliases.append(alias)
        result[name] = aliases
    return result


def _atomic_write_json(path: Path, data: Mapping[str, list[str]]) -> None:
    """在 custom 文件同目录内写临时文件，再原子替换目标。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except (OSError, TypeError, ValueError):
        temporary.unlink(missing_ok=True)
        raise


def _append_unique(values: list[str], extra: tuple[str, ...]) -> tuple[str, ...]:
    result = list(values)
    seen = {_alias_key(value) for value in result}
    for value in extra:
        if _alias_key(value) not in seen:
            result.append(value)
            seen.add(_alias_key(value))
    return tuple(result)


class AdminAliasService:
    """只读默认角色别名，并把管理修改写入独立 ``alias_custom.json``。"""

    def __init__(
        self,
        default_alias_path: str | Path | None = None,
        *,
        resource_root: str | Path | None = None,
        custom_path: str | Path | None = None,
        alias_custom_path: str | Path | None = None,
        weapon_alias_path: str | Path | None = None,
        weapon_custom_path: str | Path | None = None,
        refresh: Callable[[], None] | None = None,
    ) -> None:
        if default_alias_path is None:
            if resource_root is None:
                raise TypeError("default_alias_path 或 resource_root 不能为空")
            default_alias_path = Path(resource_root) / "alias" / "char_alias.json"
        self.default_alias_path = Path(default_alias_path)
        if (
            custom_path is not None
            and alias_custom_path is not None
            and Path(custom_path) != Path(alias_custom_path)
        ):
            raise ValueError("custom_path 与 alias_custom_path 不得冲突")
        selected_custom_path = custom_path or alias_custom_path
        self.custom_path = (
            Path(selected_custom_path)
            if selected_custom_path is not None
            else self.default_alias_path.parent.parent / "alias_custom.json"
        )
        if self.custom_path.resolve() == self.default_alias_path.resolve():
            raise ValueError("custom 别名文件不能覆盖默认别名文件")
        self.weapon_alias_path = Path(weapon_alias_path) if weapon_alias_path is not None else (
            self.default_alias_path.parent / "weapon_alias.json"
        )
        self.weapon_custom_path = Path(weapon_custom_path) if weapon_custom_path is not None else (
            self.custom_path.with_name("weapon_alias_custom.json")
        )
        if self.weapon_custom_path.resolve() == self.weapon_alias_path.resolve():
            raise ValueError("武器 custom 别名文件不能覆盖默认别名文件")
        self.refresh = refresh or (lambda: None)

    @property
    def alias_custom_path(self) -> Path:
        """custom 文件路径的语义别名。"""

        return self.custom_path

    def _load(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        return (
            _read_alias_mapping(self.default_alias_path),
            _read_alias_mapping(self.custom_path),
        )

    def _load_all(
        self,
    ) -> tuple[
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, list[str]],
    ]:
        char_defaults, char_custom = self._load()
        return (
            char_defaults,
            char_custom,
            _read_alias_mapping(self.weapon_alias_path),
            _read_alias_mapping(self.weapon_custom_path),
        )

    @staticmethod
    def _entry(
        canonical_name: str,
        defaults: Mapping[str, list[str]],
        custom: Mapping[str, list[str]],
    ) -> AdminAliasEntry:
        default_aliases = tuple(defaults.get(canonical_name, ()))
        custom_aliases = tuple(custom.get(canonical_name, ()))
        return AdminAliasEntry(
            canonical_name=canonical_name,
            default_aliases=default_aliases,
            custom_aliases=custom_aliases,
            effective_aliases=_append_unique(list(default_aliases), custom_aliases),
        )

    @classmethod
    def _catalog(
        cls,
        defaults: Mapping[str, list[str]],
        custom: Mapping[str, list[str]],
        weapon_defaults: Mapping[str, list[str]] | None = None,
        weapon_custom: Mapping[str, list[str]] | None = None,
    ) -> AdminAliasCatalog:
        names = list(defaults)
        names.extend(name for name in custom if name not in defaults)
        weapon_defaults = weapon_defaults or {}
        weapon_custom = weapon_custom or {}
        weapon_names = list(weapon_defaults)
        weapon_names.extend(name for name in weapon_custom if name not in weapon_defaults)
        return AdminAliasCatalog(
            tuple(cls._entry(name, defaults, custom) for name in names),
            tuple(cls._entry(name, weapon_defaults, weapon_custom) for name in weapon_names),
        )

    @staticmethod
    def _role_exists(role_name: str, defaults: Mapping[str, list[str]]) -> bool:
        return role_name in defaults

    @staticmethod
    def _owners(
        defaults: Mapping[str, list[str]],
        custom: Mapping[str, list[str]],
    ) -> dict[str, str]:
        owners: dict[str, str] = {}
        for role_name in list(defaults) + [
            name for name in custom if name not in defaults
        ]:
            owners[_alias_key(role_name)] = role_name
            for alias in (
                *defaults.get(role_name, ()),
                *custom.get(role_name, ()),
            ):
                owners.setdefault(_alias_key(alias), role_name)
        return owners

    def _write_custom(self, custom: Mapping[str, list[str]]) -> None:
        _atomic_write_json(self.custom_path, custom)

    def _write_weapon_custom(self, custom: Mapping[str, list[str]]) -> None:
        _atomic_write_json(self.weapon_custom_path, custom)

    def _refresh(self) -> None:
        self.refresh()

    async def list_aliases(
        self,
    ) -> AdminApiResponse[AdminAliasCatalog]:
        """返回默认 + custom 的角色目录。"""

        try:
            defaults, custom, weapon_defaults, weapon_custom = self._load_all()
            return AdminApiResponse.success(
                self._catalog(defaults, custom, weapon_defaults, weapon_custom),
            )
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取角色别名失败")

    async def get_catalog(self) -> AdminApiResponse[AdminAliasCatalog]:
        """``list_aliases`` 的 API 语义别名。"""

        return await self.list_aliases()

    async def add_alias(
        self,
        role_name: str,
        alias: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """为角色追加一个 custom 别名。"""

        role = _normalized_text(role_name)
        candidate = _normalized_text(alias)
        if role is None or candidate is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称和别名不能为空")
        try:
            defaults, custom = self._load()
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取角色别名失败")
        if not self._role_exists(role, defaults):
            return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
        owners = self._owners(defaults, custom)
        owner = owners.get(_alias_key(candidate))
        if owner is not None:
            if owner == role:
                return _failure(AdminErrorCode.CONFLICT, "别名已存在或属于默认别名")
            return _failure(AdminErrorCode.CONFLICT, "别名已被其他角色占用")

        updated = {name: list(values) for name, values in custom.items()}
        updated.setdefault(role, []).append(candidate)
        try:
            self._write_custom(updated)
            self._refresh()
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "保存自定义别名失败")
        return AdminApiResponse.success(self._entry(role, defaults, updated))

    async def delete_alias(
        self,
        role_name: str,
        alias: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """删除指定角色的 custom 别名，默认别名永远不可删除。"""

        role = _normalized_text(role_name)
        candidate = _normalized_text(alias)
        if role is None or candidate is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称和别名不能为空")
        try:
            defaults, custom = self._load()
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取角色别名失败")
        if not self._role_exists(role, defaults):
            return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
        candidate_key = _alias_key(candidate)
        if any(_alias_key(value) == candidate_key for value in defaults.get(role, ())):
            return _failure(AdminErrorCode.CONFLICT, "默认别名不可删除")
        values = custom.get(role, [])
        index = next(
            (
                idx
                for idx, value in enumerate(values)
                if _alias_key(value) == candidate_key
            ),
            None,
        )
        if index is None:
            return _failure(AdminErrorCode.NOT_FOUND, "自定义别名不存在")
        updated = {name: list(items) for name, items in custom.items()}
        updated[role].pop(index)
        if not updated[role]:
            updated.pop(role)
        try:
            self._write_custom(updated)
            self._refresh()
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "保存自定义别名失败")
        return AdminApiResponse.success(self._entry(role, defaults, updated))

    async def restore_role(
        self,
        role_name: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """仅删除一个角色的 custom 追加。"""

        role = _normalized_text(role_name)
        if role is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名称不能为空")
        try:
            defaults, custom = self._load()
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取角色别名失败")
        if not self._role_exists(role, defaults):
            return _failure(AdminErrorCode.NOT_FOUND, "角色不存在")
        updated = {name: list(items) for name, items in custom.items()}
        updated.pop(role, None)
        try:
            self._write_custom(updated)
            self._refresh()
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "恢复角色默认别名失败")
        return AdminApiResponse.success(self._entry(role, defaults, updated))

    async def restore_all(self) -> AdminApiResponse[AdminAliasCatalog]:
        """删除角色和武器全部 custom 追加，不修改默认资源文件。"""

        try:
            defaults, _custom, weapon_defaults, _weapon_custom = self._load_all()
            self._write_custom({})
            self._write_weapon_custom({})
            self._refresh()
            return AdminApiResponse.success(
                self._catalog(defaults, {}, weapon_defaults, {}),
            )
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取角色别名失败")
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "恢复默认角色别名失败")

    async def add_weapon_alias(
        self,
        weapon_name: str,
        alias: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """为武器追加一个独立持久化的 custom 别名。"""

        weapon = _normalized_text(weapon_name)
        candidate = _normalized_text(alias)
        if weapon is None or candidate is None:
            return _failure(AdminErrorCode.VALIDATION, "武器名称和别名不能为空")
        try:
            defaults = _read_alias_mapping(self.weapon_alias_path)
            custom = _read_alias_mapping(self.weapon_custom_path)
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取武器别名失败")
        if weapon not in defaults:
            return _failure(AdminErrorCode.NOT_FOUND, "武器不存在")
        owners = self._owners(defaults, custom)
        owner = owners.get(_alias_key(candidate))
        if owner is not None:
            return _failure(AdminErrorCode.CONFLICT, "别名已存在或属于默认别名")
        updated = {name: list(values) for name, values in custom.items()}
        updated.setdefault(weapon, []).append(candidate)
        try:
            self._write_weapon_custom(updated)
            self._refresh()
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "保存自定义武器别名失败")
        return AdminApiResponse.success(self._entry(weapon, defaults, updated))

    async def delete_weapon_alias(
        self,
        weapon_name: str,
        alias: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """仅删除武器 custom 别名，默认资源永远不可删除。"""

        weapon = _normalized_text(weapon_name)
        candidate = _normalized_text(alias)
        if weapon is None or candidate is None:
            return _failure(AdminErrorCode.VALIDATION, "武器名称和别名不能为空")
        try:
            defaults = _read_alias_mapping(self.weapon_alias_path)
            custom = _read_alias_mapping(self.weapon_custom_path)
        except AliasStorageError:
            return _failure(AdminErrorCode.INTERNAL, "读取武器别名失败")
        if weapon not in defaults:
            return _failure(AdminErrorCode.NOT_FOUND, "武器不存在")
        candidate_key = _alias_key(candidate)
        if any(_alias_key(value) == candidate_key for value in defaults.get(weapon, ())):
            return _failure(AdminErrorCode.CONFLICT, "默认别名不可删除")
        values = custom.get(weapon, [])
        index = next(
            (idx for idx, value in enumerate(values) if _alias_key(value) == candidate_key),
            None,
        )
        if index is None:
            return _failure(AdminErrorCode.NOT_FOUND, "自定义武器别名不存在")
        updated = {name: list(items) for name, items in custom.items()}
        updated[weapon].pop(index)
        if not updated[weapon]:
            updated.pop(weapon)
        try:
            self._write_weapon_custom(updated)
            self._refresh()
        except OSError:
            return _failure(AdminErrorCode.INTERNAL, "保存自定义武器别名失败")
        return AdminApiResponse.success(self._entry(weapon, defaults, updated))

    async def reload_defaults(self) -> AdminApiResponse[AdminAliasCatalog]:
        """重新读取默认资源，保留角色和武器 custom 文件。"""

        self._refresh()
        return await self.list_aliases()

    async def recover_aliases(self, *, force: bool) -> AdminApiResponse[AdminAliasCatalog]:
        """普通恢复保留 custom；强制恢复清空两类 custom 层。"""

        if not force:
            return await self.reload_defaults()
        return await self.restore_all()

    async def add_or_delete_alias(
        self,
        action: str,
        alias_type: str,
        name: str,
        alias: str,
    ) -> AdminApiResponse[AdminAliasEntry]:
        """把聊天命令映射到角色或武器的别名写操作。"""

        if action == "添加":
            if alias_type == "武器":
                return await self.add_weapon_alias(name, alias)
            return await self.add_alias(name, alias)
        if action == "删除":
            if alias_type == "武器":
                return await self.delete_weapon_alias(name, alias)
            return await self.delete_alias(name, alias)
        return _failure(AdminErrorCode.VALIDATION, "别名操作无效")

    # 给不同 Web adapter 保留清晰的动作名，所有入口共用同一实现。
    list = list_aliases
    add_custom_alias = add_alias
    delete_custom_alias = delete_alias
    restore_defaults = restore_all
    restore_all_aliases = restore_all
    restore_role_aliases = restore_role


AliasAdminService = AdminAliasService
AliasCatalog = AdminAliasCatalog
AliasEntry = AdminAliasEntry


__all__ = [
    "AdminAliasCatalog",
    "AdminAliasEntry",
    "AdminAliasService",
    "AliasAdminService",
    "AliasCatalog",
    "AliasEntry",
    "AliasStorageError",
]
