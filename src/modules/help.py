"""v0.1 帮助 use case。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ..entry.response import ImageResponse, write_temporary_image


async def help_use_case(
    request: CommandRequest,
    registry: CommandRegistry,
    **_parameters: Any,
) -> ImageResponse:
    """使用 DNAUID 原版帮助卡片绘制器输出图片。"""

    from ..infrastructure.rendering.help import get_help

    payload = await get_help()
    rendered_root = request.services.get("rendered_root")
    if not isinstance(rendered_root, (str, Path)):
        raise RuntimeError("帮助卡缺少受控渲染目录")
    return write_temporary_image(
        rendered_root,
        payload,
        prefix="dnaby-help-帮助-",
        suffix=".jpg",
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
