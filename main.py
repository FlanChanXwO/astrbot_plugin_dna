"""AstrBot 插件薄入口。

命令、Web 路由、配置和业务生命周期由 ``src`` 分层负责；本文件只保留
AstrBot ``Star`` 适配和 runtime 组装。
"""

from __future__ import annotations

from typing import Any

from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig

if __package__:
    from .src.bootstrap import PluginRuntime, build_runtime
    from .src.entry.commands import (
        CommandRegistry,
        install_command_handlers,
        load_command_registry,
    )
    from .src.entry.web import WebRegistrar
else:
    from src.bootstrap import PluginRuntime, build_runtime
    from src.entry.commands import (
        CommandRegistry,
        install_command_handlers,
        load_command_registry,
    )
    from src.entry.web import WebRegistrar


COMMAND_REGISTRY: CommandRegistry = load_command_registry()


class DnabyPlugin(Star):
    """二重螺旋的 AstrBot 插件入口。"""

    name = "astrbot_plugin_dna"

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config
        self._runtime: PluginRuntime = build_runtime(
            context,
            config,
            command_registry=COMMAND_REGISTRY,
            plugin_context=self,
        )

    async def initialize(self) -> None:
        """由 AstrBot 调用，启动插件 runtime。"""

        await self._runtime.initialize()

    async def terminate(self) -> None:
        """由 AstrBot 调用，停止插件 runtime 并撤销 Dashboard Web 路由。"""

        try:
            await self._runtime.terminate()
        finally:
            WebRegistrar.unregister_plugin_routes(self.context, self.name)


install_command_handlers(DnabyPlugin, COMMAND_REGISTRY)


__all__ = ["COMMAND_REGISTRY", "DnabyPlugin"]
