"""Goal 5 Task 09：renderer 接入与 incomplete 语义审计契约。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.entry.commands import CommandRegistry, CommandRequest
from src.entry.response import ImageResponse
from src.infrastructure.rendering.artifact_store import read_rendered_artifact
from src.infrastructure.rendering.encyclopedia import EncyclopediaRenderer
from src.infrastructure.rendering.notices import NoticesRenderer
from src.infrastructure.rendering.player import PlayerRenderer
from src.infrastructure.rendering.runtime_assets import resources_incomplete
from src.infrastructure.resources.encyclopedia import EncyclopediaResourceStore
from src.infrastructure.resources.resolver import ResolvedAsset
from src.modules.help import help_use_case


@dataclass
class MissingResolver:
    """返回显式 missing，模拟没有 verified snapshot 的请求级 resolver。"""

    def resolve(self, logical_key: str) -> ResolvedAsset:
        del logical_key
        return ResolvedAsset(
            path=None,
            source="none",
            status="missing",
            incomplete=True,
        )


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (240, 240, 240)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_resources_incomplete_treats_legacy_fallback_as_incomplete() -> None:
    """旧 renderer 的 fallback/missing 记录不能被误判为完整卡片。"""

    assert resources_incomplete([{"kind": "font", "status": "fallback"}]) is True
    assert resources_incomplete([{"kind": "font", "status": "missing"}]) is True
    assert resources_incomplete(
        [{"kind": "font", "status": "fallback", "incomplete": "false"}],
    ) is False


def test_legacy_renderers_mark_builtin_font_fallback_incomplete(tmp_path: Path) -> None:
    """Player/百科/公告共用的旧字体 fallback 必须进入 incomplete 语义。"""

    resources = EncyclopediaResourceStore()
    renderers = (
        PlayerRenderer(tmp_path / "player", resources),
        EncyclopediaRenderer(tmp_path / "encyclopedia", resources),
        NoticesRenderer(tmp_path / "notices", resources),
    )

    for renderer in renderers:
        record = renderer._font_resource()
        assert record["status"] == "fallback"
        assert record["incomplete"] == "true"


@pytest.mark.asyncio
async def test_help_use_case_marks_missing_resolver_assets_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帮助卡使用 placeholder 时必须把资源状态写入 artifact 并阻止完整缓存语义。"""

    import src.infrastructure.rendering.help as help_rendering

    monkeypatch.setattr(
        help_rendering,
        "_load_help_data",
        lambda: {"基础": {"desc": "", "data": [{"name": "状态", "eg": "状态"}]}},
    )

    async def fake_render(*_: object, **__: object) -> bytes:
        return _jpeg_bytes()

    monkeypatch.setattr(help_rendering._RENDERER, "render", fake_render)
    request = CommandRequest(
        command_id="help",
        text="kk帮助",
        parameters={},
        services={
            "rendered_root": tmp_path / "rendered",
            "bind_resource_resolver": lambda: nullcontext(MissingResolver()),
        },
    )

    response = await help_use_case(request, CommandRegistry(()))

    assert isinstance(response, ImageResponse)
    assert response.incomplete is True
    artifact = read_rendered_artifact(response.image)
    resources = artifact.metadata["dnaby.resources"]
    assert isinstance(resources, list)
    assert resources
    assert any(item["status"] == "placeholder" for item in resources)
