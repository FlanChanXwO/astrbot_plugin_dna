"""v0.1 帮助 use case。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from ..entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ..entry.response import ImageResponse
from ..infrastructure.rendering.artifact import RenderedArtifact
from ..infrastructure.rendering.artifact_store import write_rendered_artifact
from ..version import PLUGIN_VERSION

HelpRenderer = Callable[[str], Awaitable[bytes]]


def _help_renderer(request: CommandRequest) -> HelpRenderer:
    """解析帮助卡渲染 seam；默认实现仍按需从基础设施模块加载。"""

    renderer = request.services.get("help_renderer")
    if renderer is None:
        from ..infrastructure.rendering.help import get_help

        return get_help
    if not callable(renderer):
        raise TypeError("帮助卡渲染器不可用")
    return cast(HelpRenderer, renderer)


async def help_use_case(
    request: CommandRequest,
    registry: CommandRegistry,
    **_parameters: Any,
) -> ImageResponse:
    """使用 DNAUID 原版帮助卡片绘制器输出图片。"""

    renderer = request.services.get("help_renderer")
    if renderer is None:
        from ..infrastructure.rendering.help import get_help

        payload = await get_help(
            prefix=request.matched_prefix,
            registry=registry,
            permission=request.permission,
            version=PLUGIN_VERSION,
        )
    else:
        payload = await _help_renderer(request)(request.matched_prefix)
    rendered_root = request.services.get("rendered_root")
    if not isinstance(rendered_root, (str, Path)):
        raise TypeError("帮助卡缺少受控渲染目录")
    artifact = RenderedArtifact.from_bytes(
        payload,
        media_type="image/jpeg",
        metadata={
            "dnaby.text": "",
            "dnaby.layout": {"width": 2020, "height": None, "sections": []},
            "dnaby.resources": [],
        },
    )
    return write_rendered_artifact(
        rendered_root,
        artifact,
        prefix="dnaby-help-帮助-",
    )


COMMAND_SPECS = (
    CommandSpec(
        id="help",
        pattern=r"^帮助$",
        group="bot主人功能",
        name="帮助",
        description="查看当前已实现命令",
        examples=("帮助",),
        permission="user",
        use_case=help_use_case,
    ),
)


__all__ = ["COMMAND_SPECS", "help_use_case"]
