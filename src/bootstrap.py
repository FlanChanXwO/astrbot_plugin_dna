"""应用 runtime 组装入口。

``main.py`` 只负责 AstrBot ``Star`` 生命周期；所有入口扩展点在这里组装，
后续配置、持久化和业务模块按阶段加入，不让入口文件重新膨胀。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from astrbot.api.star import Context
from astrbot.core import AstrBotConfig

from .entry.commands import CommandRegistry, load_command_registry
from .entry.event import EmptyEventEntryPoint, EventEntryPoint
from .entry.lifecycle import PluginLifecycle
from .entry.response import ResponseFactory
from .entry.web import WebRegistrar
from .infrastructure.config import DnabySettings
from .infrastructure.http import DnaApiAccountTransport
from .infrastructure.persistence import AsyncDatabase
from .infrastructure.resources.paths import PLUGIN_NAME
from .modules.account import AccountService
from .modules.account.contracts import AccountTransport
from .modules.privacy import PrivacyService

PluginConfig = AstrBotConfig | dict[str, Any] | None


@dataclass(slots=True)
class PluginRuntime:
    """一个插件实例的入口运行时。"""

    context: Context
    config: PluginConfig
    lifecycle: PluginLifecycle
    events: EventEntryPoint
    responses: ResponseFactory
    commands: CommandRegistry
    settings: DnabySettings
    services: Mapping[str, object]

    async def initialize(self) -> None:
        """启动 runtime 扩展点。"""

        await self.lifecycle.initialize()

    async def terminate(self) -> None:
        """停止 runtime 扩展点。"""

        await self.lifecycle.terminate()


def build_runtime(
    context: Context,
    config: PluginConfig,
    command_registry: CommandRegistry | None = None,
    *,
    database: AsyncDatabase | None = None,
    account_transport: AccountTransport | None = None,
    services: Mapping[str, object] | None = None,
) -> PluginRuntime:
    """为一个 AstrBot 插件实例组装代码 registry 和 typed services。"""

    settings = DnabySettings.from_config(config)
    runtime_database = database
    if runtime_database is None:
        from astrbot.api.star import StarTools

        runtime_database = AsyncDatabase.from_data_dir(
            StarTools.get_data_dir(PLUGIN_NAME),
        )
    account_service = AccountService(
        runtime_database,
        account_transport or DnaApiAccountTransport(),
        max_bind_count=settings.login.max_bind_count,
    )
    privacy_service = PrivacyService(
        runtime_database,
        allow_mention_query=settings.display.allow_mention_query,
    )
    resolved_services: dict[str, object] = {
        "database": runtime_database,
        "account_service": account_service,
        "privacy_service": privacy_service,
    }
    if services is not None:
        resolved_services.update(services)

    web = WebRegistrar(context)
    lifecycle = PluginLifecycle(
        start_hooks=(web.initialize,),
        stop_hooks=(runtime_database.dispose,),
    )
    return PluginRuntime(
        context=context,
        config=config,
        lifecycle=lifecycle,
        events=EmptyEventEntryPoint(),
        responses=ResponseFactory(),
        commands=(
            command_registry
            if command_registry is not None
            else load_command_registry()
        ),
        settings=settings,
        services=resolved_services,
    )
