import asyncio
import json
from typing import Any

from ...utils.name_convert import (
    alias_to_char_name,
    alias_to_weapon_name,
    builtin_alias_list,
)
from ...utils.resource.RESOURCE_PATH import CHAR_ALIAS_PATH, WEAPON_ALIAS_PATH


async def _read_json(path) -> dict[str, Any]:
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError(f"别名文件不是 JSON 对象: {path}")
    return data


async def _write_json(path, data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    await asyncio.to_thread(path.write_text, text, encoding="utf-8")


async def action_char_alias(action: str, char_name: str, new_alias: str) -> str:
    if not CHAR_ALIAS_PATH.exists():
        return "别名配置文件不存在，请检查文件路径"

    data = await _read_json(CHAR_ALIAS_PATH)

    std_char_name = alias_to_char_name(char_name)
    if not std_char_name:
        return f"角色【{char_name}】不存在，请检查名称"

    if action == "添加":
        check_new_alias = alias_to_char_name(new_alias)
        if check_new_alias:
            return f"别名【{new_alias}】已被角色【{check_new_alias}】占用"

        data.setdefault(std_char_name, []).append(new_alias)
        await _write_json(CHAR_ALIAS_PATH, data)
        return f"成功为角色【{char_name}】添加别名【{new_alias}】"

    elif action == "删除":
        if new_alias in data.get(std_char_name, []):
            data[std_char_name].remove(new_alias)
            await _write_json(CHAR_ALIAS_PATH, data)
            return f"成功为角色【{std_char_name}】删除别名【{new_alias}】"

        if new_alias in builtin_alias_list(std_char_name):
            return f"别名【{new_alias}】为内置别名，无法删除"
        return f"别名【{new_alias}】不存在，无法删除"

    return "未知操作，仅支持「添加」或「删除」"


async def action_weapon_alias(action: str, weapon_name: str, new_alias: str) -> str:
    if not WEAPON_ALIAS_PATH.exists():
        return "别名配置文件不存在，请检查文件路径"

    data = await _read_json(WEAPON_ALIAS_PATH)

    std_weapon_name = alias_to_weapon_name(weapon_name)
    if not std_weapon_name:
        return f"武器【{weapon_name}】不存在，请检查名称"

    if action == "添加":
        check_new_alias = alias_to_weapon_name(new_alias)
        if check_new_alias:
            return f"别名【{new_alias}】已被武器【{check_new_alias}】占用"

        data.setdefault(std_weapon_name, []).append(new_alias)
        await _write_json(WEAPON_ALIAS_PATH, data)
        return f"成功为武器【{weapon_name}】添加别名【{new_alias}】"

    elif action == "删除":
        if new_alias in data.get(std_weapon_name, []):
            data[std_weapon_name].remove(new_alias)
            await _write_json(WEAPON_ALIAS_PATH, data)
            return f"成功为武器【{std_weapon_name}】删除别名【{new_alias}】"

        if new_alias in builtin_alias_list(std_weapon_name):
            return f"别名【{new_alias}】为内置别名，无法删除"
        return f"别名【{new_alias}】不存在，无法删除"

    return "未知操作，仅支持「添加」或「删除」"
