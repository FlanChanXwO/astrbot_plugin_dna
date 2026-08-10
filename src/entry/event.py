"""事件入口边界。

v0.1 只建立边界，不注册命令。命令解析和真正的 async-generator handler
在后续 registry/use-case task 中加入。
"""

from __future__ import annotations

from typing import Any, Protocol


class EventEntryPoint(Protocol):
    """业务事件入口的最小公共协议。"""

    async def handle(self, event: Any) -> None:
        """处理一个 AstrBot 事件。"""


class EmptyEventEntryPoint:
    """没有命令注册时使用的显式空入口。"""

    async def handle(self, event: Any) -> None:
        """v0.1 没有可处理的命令，故不产生框架响应。"""

