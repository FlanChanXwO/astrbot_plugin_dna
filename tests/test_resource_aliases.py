"""新版角色规范名包含旧名时，保持独立且不放开冲突别名。"""

import json

import pytest

from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.generation import (
    ResourceGenerationError,
    _validate_alias_file,
)


def test_extended_canonical_names_remain_independently_resolvable(tmp_path):
    path = tmp_path / "alias" / "char_alias.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"黎瑟": ["黎瑟"], "黎瑟·浴火": ["黎瑟·浴火"]}))
    _validate_alias_file(path)
    catalog = EncyclopediaResourceStore.from_root(tmp_path).aliases
    assert catalog.resolve_char("黎瑟") == "黎瑟"
    assert catalog.resolve_char("黎瑟·浴火") == "黎瑟·浴火"


@pytest.mark.parametrize("alias", ["黎瑟", "黎瑟的别名"])
def test_extended_names_do_not_allow_cross_character_alias_collisions(tmp_path, alias):
    path = tmp_path / "char_alias.json"
    path.write_text(json.dumps({"黎瑟": ["黎瑟"], "黎瑟·浴火": [alias]}))
    with pytest.raises(ResourceGenerationError, match="歧义"):
        _validate_alias_file(path)
