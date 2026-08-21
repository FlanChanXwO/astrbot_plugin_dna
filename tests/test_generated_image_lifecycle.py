"""帮助卡与更新日志图片必须进入 AstrBot 可追踪的临时文件生命周期。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.entry.commands import CommandRegistry, CommandRequest
from src.entry.response import ImageResponse, ResponseFactory
from src.infrastructure.resources import ResourceSyncResult
from src.modules.help import help_use_case
from src.modules.operations.resource_service import ResourceUpdateService


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
async def test_help_image_is_tracked_and_cleaned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def render_help() -> bytes:
        return b"help-image"

    monkeypatch.setattr("src.infrastructure.rendering.help.get_help", render_help)
    rendered_root = tmp_path / "rendered"
    request = CommandRequest(
        command_id="help",
        text="kk帮助",
        parameters={},
        services={"rendered_root": rendered_root},
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


@pytest.mark.asyncio
async def test_update_log_image_is_tracked_and_cleaned(tmp_path: Path) -> None:
    rendered_root = tmp_path / "rendered"
    service = ResourceUpdateService(
        repo_root=tmp_path / "repo",
        rendered_root=rendered_root,
        synchronize=lambda: ResourceSyncResult(
            repository=tmp_path / "repo",
            action="cloned",
            resource_version="test",
        ),
        commit_log=lambda _root: ["abc123 fix"],
    )

    response = await service.update_log(None)

    assert isinstance(response, ImageResponse)
    assert response.temporary is True
    assert Path(response.image).parent == rendered_root
    event = CleanupEvent()
    ResponseFactory(temporary_roots=(rendered_root,)).build(event, response)
    assert event.tracked == [str(response.image)]
    event.cleanup_temporary_local_files()
    assert not Path(response.image).exists()
