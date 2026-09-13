"""Help 卡缓存的 generation 失效契约。"""

from __future__ import annotations

from types import SimpleNamespace

from src.infrastructure.rendering.help import help_cache_generation_id


def test_help_cache_generation_id_prefers_resolver_identity() -> None:
    """缓存键必须使用稳定的 generation 标识，而不是 Python 对象 id。"""

    first = SimpleNamespace(generation_id="a" * 40)
    second = SimpleNamespace(generation_id="a" * 40)
    third = SimpleNamespace(generation_id="b" * 40)
    plain = SimpleNamespace()

    assert help_cache_generation_id(first) == help_cache_generation_id(second)
    assert help_cache_generation_id(first) != help_cache_generation_id(third)
    # 没有 generation 信息的 resolver 必须退化到对象身份，避免跨代缓存误命中。
    assert help_cache_generation_id(plain) != help_cache_generation_id(
        SimpleNamespace()
    )
    assert help_cache_generation_id(None) is None
