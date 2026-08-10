"""别名数据异步文件边界测试。"""

import asyncio
import json
from pathlib import Path


def test_char_alias_mutation_persists_json_without_changing_lookup(monkeypatch, tmp_path: Path):
    from dnaby.dna_alias import alias_ops
    from dnaby.utils import name_convert

    alias_path = tmp_path / "char_alias.json"
    alias_path.write_text('{"角色": ["角色"]}', encoding="utf-8")
    monkeypatch.setattr(alias_ops, "CHAR_ALIAS_PATH", alias_path)
    monkeypatch.setattr(name_convert, "char_alias_data", {"角色": ["角色"]})
    monkeypatch.setattr(name_convert, "builtin_char_alias_data", {})

    result = asyncio.run(alias_ops.action_char_alias("添加", "角色", "新别名"))

    assert result == "成功为角色【角色】添加别名【新别名】"
    assert json.loads(alias_path.read_text(encoding="utf-8"))["角色"] == ["角色", "新别名"]
