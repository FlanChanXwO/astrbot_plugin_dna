"""帮助卡图片必须进入 AstrBot 可追踪的临时文件生命周期。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.commands import CommandRegistry, CommandRequest
from src.entry.response import ImageResponse, ResponseFactory
from src.modules.help import help_use_case


class CleanupEvent:
    def __init__(self) -> None:
        self.tracked: list[str] = []

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(path)

    def image_result(self, image: object) -> object:
        return image

    def cleanup_temporary_local_files(self) -> None:
        for path in self.tracked:
            Path(path).unlink()
        self.tracked.clear()


@pytest.mark.asyncio
async def test_help_use_case_accepts_injected_renderer(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    async def render_help(prefix: str) -> bytes:
        calls.append(prefix)
        return b"help-image"

    rendered_root = tmp_path / "rendered"
    request = CommandRequest(
        command_id="help",
        text="dna帮助",
        parameters={},
        services={"rendered_root": rendered_root, "help_renderer": render_help},
        matched_prefix="dna",
    )

    response = await help_use_case(request, CommandRegistry(()))

    assert calls == ["dna"]
    assert isinstance(response, ImageResponse)
    assert Path(response.image).read_bytes() == b"help-image"


@pytest.mark.asyncio
async def test_help_image_is_tracked_and_cleaned(tmp_path: Path) -> None:
    async def render_help(prefix: str) -> bytes:
        assert prefix == "kk"
        return b"help-image"

    rendered_root = tmp_path / "rendered"
    request = CommandRequest(
        command_id="help",
        text="kk帮助",
        parameters={},
        services={"rendered_root": rendered_root, "help_renderer": render_help},
    )

    response = await help_use_case(request, CommandRegistry(()))

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    assert Path(response.image).parent == rendered_root
    event = CleanupEvent()
    ResponseFactory(temporary_roots=(rendered_root,)).build(event, response)
    assert event.tracked == [str(response.image)]
    event.cleanup_temporary_local_files()
    assert not Path(response.image).exists()
