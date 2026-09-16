"""帮助渲染的 presentation 接入、generation 缓存隔离与 incomplete 恢复契约。

渲染器被替换为桩实现，只验证 help.py 自身的缓存与资源记录语义，
不做真实 T2I 渲染。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from main import COMMAND_REGISTRY
from src.infrastructure.rendering import help as help_module
from src.infrastructure.rendering.static_assets import ResolvedStaticAsset


class _FakeResolver:
    """按 key 映射提供素材的 resolver 桩；generation_id 用于缓存隔离验证。"""

    def __init__(
        self,
        provided: dict[str, Path],
        *,
        generation_id: str,
    ) -> None:
        self.provided = provided
        self._generation_id = generation_id

    @property
    def generation_id(self) -> str:
        return self._generation_id

    def resolve(self, logical_key: str) -> ResolvedStaticAsset:
        path = self.provided.get(logical_key)
        if path is not None:
            return ResolvedStaticAsset(path, "verified_snapshot", False)
        return ResolvedStaticAsset(None, "none", True)

    def resolve_relative(self, relative: str) -> ResolvedStaticAsset:
        path = self.provided.get(relative)
        if path is not None:
            return ResolvedStaticAsset(path, "verified_snapshot", False)
        return ResolvedStaticAsset(None, "none", True)


class _FakeRenderer:
    """记录渲染次数并输出固定字节的渲染器桩。"""

    def __init__(self) -> None:
        self.calls = 0
        self.last_data: dict[str, Any] | None = None

    async def render(self, _template: str, _data: Any, _spec: Any) -> bytes:
        self.calls += 1
        self.last_data = _data
        return b"help-payload"


@pytest.fixture
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> _FakeRenderer:
    renderer = _FakeRenderer()
    monkeypatch.setattr(help_module, "_RENDERER", renderer)
    return renderer


@pytest.fixture(autouse=True)
def _clear_help_cache() -> None:
    help_module.invalidate_help_cache()


@pytest.mark.asyncio
async def test_help_header_uses_canonical_plugin_logo(
    fake_renderer: _FakeRenderer,
) -> None:
    """帮助卡左上角必须使用仓库根目录的插件 Logo。"""

    resolver = _FakeResolver({}, generation_id="gen-logo")
    await help_module.get_help(
        "dna",
        registry=COMMAND_REGISTRY,
        permission="user",
        asset_resolver=resolver,
    )

    assert fake_renderer.last_data is not None
    icon_uri = fake_renderer.last_data["icon"]
    _prefix, encoded = icon_uri.split(",", maxsplit=1)
    assert base64.b64decode(encoded) == (Path(__file__).parents[1] / "logo.png").read_bytes()


@pytest.mark.asyncio
async def test_help_cache_hit_restores_resource_records(
    monkeypatch: pytest.MonkeyPatch,
    fake_renderer: _FakeRenderer,
) -> None:
    """缓存命中后必须恢复完整的资源记录，不得丢失 incomplete 状态。"""

    resolver = _FakeResolver(
        {"textures/help/icon/登录.png": Path(__file__).parents[1] / "logo.png"},
        generation_id="gen-a",
    )

    first_records: list[dict[str, str]] = []
    first = await help_module.get_help(
        "dna",
        registry=COMMAND_REGISTRY,
        permission="user",
        asset_resolver=resolver,
        resource_records=first_records,
    )
    assert first == b"help-payload"
    assert fake_renderer.calls == 1
    assert first_records, "完整渲染必须产生资源记录"
    assert any(record["key"] == "texture.help.icon:登录.png" for record in first_records)

    second_records: list[dict[str, str]] = []
    second = await help_module.get_help(
        "dna",
        registry=COMMAND_REGISTRY,
        permission="user",
        asset_resolver=resolver,
        resource_records=second_records,
    )
    assert second == b"help-payload"
    assert fake_renderer.calls == 1, "同 generation 的重复请求必须命中缓存"
    assert second_records == first_records, "缓存命中后资源记录不得丢失或变形"


@pytest.mark.asyncio
async def test_help_cache_is_isolated_between_generations(
    monkeypatch: pytest.MonkeyPatch,
    fake_renderer: _FakeRenderer,
) -> None:
    """不同 resource generation 不得共用帮助图片缓存。"""

    icon = Path(__file__).parents[1] / "logo.png"

    async def render_for_generation(gen: str) -> bytes:
        return await help_module.get_help(
            "dna",
            registry=COMMAND_REGISTRY,
            permission="user",
            asset_resolver=_FakeResolver(
                {"textures/help/icon/登录.png": icon},
                generation_id=gen,
            ),
        )

    first = await render_for_generation("gen-a")
    second = await render_for_generation("gen-b")
    assert fake_renderer.calls == 2, "generation 切换必须重新渲染"
    assert first == second == b"help-payload"


@pytest.mark.asyncio
async def test_help_missing_static_assets_degrade_with_incomplete_records(
    monkeypatch: pytest.MonkeyPatch,
    fake_renderer: _FakeRenderer,
) -> None:
    """无快照时静态素材缺失必须降级为 placeholder 并标记 incomplete。"""

    # 空 resolver：没有任何 snapshot 素材可解析。
    resolver = _FakeResolver({}, generation_id="gen-empty")
    records: list[dict[str, str]] = []
    payload = await help_module.get_help(
        "dna",
        registry=COMMAND_REGISTRY,
        permission="user",
        asset_resolver=resolver,
        resource_records=records,
    )
    assert payload == b"help-payload"
    assert records, "缺失素材也必须产生资源记录"
    incomplete = [record for record in records if record["incomplete"] == "true"]
    assert incomplete, "缺失素材必须标记 incomplete"
    assert any(record["status"] == "fallback" for record in incomplete)
