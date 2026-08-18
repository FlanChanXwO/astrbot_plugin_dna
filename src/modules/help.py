"""v0.1 帮助 use case。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ..entry.response import ImageResponse


async def help_use_case(
    _request: CommandRequest,
    registry: CommandRegistry,
    **_parameters: Any,
) -> ImageResponse:
    """使用 DNAUID 原版帮助卡片绘制器输出图片。"""

    from ..infrastructure.rendering.help import get_help

    payload = await get_help()
    with tempfile.NamedTemporaryFile(prefix="dnaby-help-帮助-", suffix=".jpg", delete=False) as file:
        file.write(payload)
        return ImageResponse(str(Path(file.name)), temporary=False)


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
