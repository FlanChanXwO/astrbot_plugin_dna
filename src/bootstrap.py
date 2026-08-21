"""应用 runtime 组装入口。

``main.py`` 只负责 AstrBot ``Star`` 生命周期；所有入口扩展点在这里组装，
后续配置、持久化和业务模块按阶段加入，不让入口文件重新膨胀。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api.star import Context
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import Image as AstrImage
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain

from .entry.commands import CommandRegistry, load_command_registry
from .entry.event import EmptyEventEntryPoint, EventEntryPoint
from .entry.lifecycle import PluginLifecycle
from .entry.response import ResponseFactory
from .entry.web import WebRegistrar
from .infrastructure.config import DnabySettings
from .infrastructure.http import (
    DnaApiAccountTransport,
    DnaApiCheckinTransport,
    DnaApiEncyclopediaTransport,
    DnaApiNoticesTransport,
    DnaApiPlayerTransport,
)
from .infrastructure.notices_scheduler import NoticesScheduler
from .infrastructure.persistence import AsyncDatabase
from .infrastructure.rendering import (
    CheckinRenderer,
    EncyclopediaRenderer,
    NoticesRenderer,
    PlayerRenderer,
    ResourceMap,
)
from .infrastructure.resources import EncyclopediaResourceStore, ResourceManifest
from .infrastructure.resources.paths import PLUGIN_NAME, resource_repository_dir
from .infrastructure.scheduler import SignScheduler
from .infrastructure.subscriptions import SubscriptionStore
from .modules.account import AccountService
from .modules.account.contracts import AccountTransport
from .modules.checkin.contracts import CheckinTransport
from .modules.checkin.service import CheckinService
from .modules.encyclopedia.contracts import EncyclopediaTransport
from .modules.encyclopedia.service import EncyclopediaService
from .modules.notices.ann_state import AnnStateStore
from .modules.notices.contracts import NoticesTransport
from .modules.notices.service import NoticesService
from .modules.operations.alias_service import AliasService
from .modules.operations.resource_service import ResourceUpdateService
from .modules.operations.service import PanelService
from .modules.player.contracts import PlayerTransport
from .modules.player.service import PlayerService
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
    player_transport: PlayerTransport | None = None,
    encyclopedia_transport: EncyclopediaTransport | None = None,
    checkin_transport: CheckinTransport | None = None,
    notices_transport: NoticesTransport | None = None,
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
    resource_root = resource_repository_dir(runtime_database.path.parent)
    if resource_root.exists():
        ResourceManifest.load(
            resource_root / "resource_manifest.json",
        ).validate_runtime_layout(resource_root)
    player_resources = ResourceMap.from_root(resource_root)
    encyclopedia_resources = EncyclopediaResourceStore.from_root(resource_root)
    player_service = PlayerService(
        runtime_database,
        player_transport or DnaApiPlayerTransport(runtime_database),
        privacy_service,
        PlayerRenderer(runtime_database.path.parent / "rendered", player_resources),
        show_unowned_roles=settings.display.show_unowned_roles,
    )
    encyclopedia_service = EncyclopediaService(
        runtime_database,
        encyclopedia_transport or DnaApiEncyclopediaTransport(runtime_database),
        privacy_service,
        EncyclopediaRenderer(runtime_database.path.parent / "rendered", encyclopedia_resources),
        encyclopedia_resources,
        guide_providers=tuple(settings.display.guide_providers),
    )
    checkin_service = CheckinService(
        runtime_database,
        checkin_transport or DnaApiCheckinTransport(runtime_database),
        privacy_service,
        CheckinRenderer(runtime_database.path.parent / "rendered", encyclopedia_resources),
        community_tasks=tuple(settings.sign_in.community_tasks),
        concurrency=settings.sign_in.concurrency,
        interval_range=settings.sign_in.concurrency_interval_seconds,
    )
    subscriptions = SubscriptionStore(runtime_database.path.parent / "subscriptions.json")
    sign_scheduler = SignScheduler(
        checkin_service,
        subscriptions,
        sign_time=settings.sign_in.sign_time,
        scheduled_enabled=settings.sign_in.scheduled_enabled,
        enable_all_users=settings.sign_in.enable_all_users,
        push=lambda origin, text: context.send_message(
            origin,
            MessageChain(chain=[Plain(text)]),
        ),
    )
    notices_service = NoticesService(
        runtime_database,
        notices_transport or DnaApiNoticesTransport(runtime_database),
        privacy_service,
        NoticesRenderer(runtime_database.path.parent / "rendered", encyclopedia_resources),
        subscriptions=subscriptions,
        ann_state=AnnStateStore(runtime_database.path.parent / "ann_state.json"),
        push=lambda origin, payload: context.send_message(
            origin,
            MessageChain(
                chain=[
                    Plain(str(payload)) if not isinstance(payload, Path) else AstrImage(str(payload)),
                ],
            ),
        ),
    )
    notices_scheduler = NoticesScheduler(
        notices_service,
        push_time=settings.notifications.secret_push_time,
        poll_minutes=settings.notifications.announcement_check_minutes,
    )

    def _resolve_char_id(char_name: str) -> str | None:
        from .utils.name_convert import char_name_to_char_id

        return char_name_to_char_id(char_name)

    def _panel_dir_for(char_id: str) -> str:
        from .utils.master_char_const import get_master_char_panel_dir

        return get_master_char_panel_dir(char_id)

    panel_service = PanelService(
        runtime_database.path.parent / "panel_custom",
        resource_root=resource_root,
        resolve_char_id=_resolve_char_id,
        panel_dir_for=_panel_dir_for,
    )

    def _synchronize_resources():
        from .infrastructure.resources import download_all_resources

        return download_all_resources(data_dir=runtime_database.path.parent)

    resource_update_service = ResourceUpdateService(
        repo_root=Path(__file__).resolve().parents[2],
        rendered_root=runtime_database.path.parent / "rendered",
        synchronize=_synchronize_resources,
    )
    alias_service = AliasService(
        resource_root / "alias",
        refresh=lambda: None,
    )
    resolved_services: dict[str, object] = {
        "database": runtime_database,
        "account_service": account_service,
        "privacy_service": privacy_service,
        "player_service": player_service,
        "resource_root": resource_root,
        "rendered_root": runtime_database.path.parent / "rendered",
        "player_resources": player_resources,
        "encyclopedia_service": encyclopedia_service,
        "encyclopedia_resources": encyclopedia_resources,
        "checkin_service": checkin_service,
        "subscriptions": subscriptions,
        "sign_scheduler": sign_scheduler,
        "notices_service": notices_service,
        "notices_scheduler": notices_scheduler,
        "panel_service": panel_service,
        "resource_update_service": resource_update_service,
        "alias_service": alias_service,
    }
    if services is not None:
        resolved_services.update(services)

    web = WebRegistrar(context)
    lifecycle = PluginLifecycle(
        start_hooks=(web.initialize, sign_scheduler.start, notices_scheduler.start),
        stop_hooks=(notices_scheduler.stop, sign_scheduler.stop, runtime_database.dispose),
    )
    return PluginRuntime(
        context=context,
        config=config,
        lifecycle=lifecycle,
        events=EmptyEventEntryPoint(),
        responses=ResponseFactory(
            temporary_roots=(runtime_database.path.parent / "rendered",),
        ),
        commands=(
            command_registry
            if command_registry is not None
            else load_command_registry()
        ),
        settings=settings,
        services=resolved_services,
    )
