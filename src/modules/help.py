"""v0.1 帮助 use case。"""

from __future__ import annotations

from typing import Any

from ..entry.commands import CommandRegistry, CommandRequest, CommandSpec
from ..entry.response import PlainTextResponse


async def help_use_case(
    _request: CommandRequest,
    registry: CommandRegistry,
    **_parameters: Any,
) -> PlainTextResponse:
    """返回当前 registry 中已实现命令的帮助文本。"""

    return PlainTextResponse(registry.render_help())


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
