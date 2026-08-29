"""应用 runtime 组装入口。

``main.py`` 只负责 AstrBot ``Star`` 生命周期；所有入口扩展点在这里组装，
后续配置、持久化和业务模块按阶段加入，不让入口文件重新膨胀。
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api.star import Context
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import At, Plain
from astrbot.core.message.components import Image as AstrImage
from astrbot.core.message.message_event_result import MessageChain

from .entry.admin_web import build_admin_web_routes
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
from .infrastructure.resources import (
    EncyclopediaResourceStore,
    ResourceManifest,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)
from .infrastructure.resources.paths import (
    PLUGIN_NAME,
    resource_generations_dir,
    resource_repository_dir,
)
from .infrastructure.scheduler import SignScheduler
from .infrastructure.scheduler_state import SchedulerRegistry
from .infrastructure.subscriptions import SubscriptionStore
from .modules.account import AccountService
from .modules.account.contracts import AccountTransport
from .modules.admin import (
    AccountDeletionCoordinator,
    AdminAccountService,
    AdminAliasService,
    AdminApiService,
    AdminPanelService,
    AdminPreviewService,
    AiocqhttpMembershipProbe,
    MembershipService,
)
from .modules.checkin.contracts import CheckinTransport
from .modules.checkin.service import CheckinService
from .modules.encyclopedia.contracts import EncyclopediaTransport
from .modules.encyclopedia.service import EncyclopediaService
from .modules.notices.ann_state import AnnStateStore
from .modules.notices.contracts import NoticesTransport
from .modules.notices.service import NoticesService
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

        try:
            await self.lifecycle.terminate()
        finally:
            from .infrastructure.rendering.help import invalidate_help_cache

            invalidate_help_cache()


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
    resource_cache_root = resource_repository_dir(runtime_database.path.parent)
    resource_snapshots = ResourceSnapshotCoordinator(
        resource_cache_root,
        generations_root=resource_generations_dir(runtime_database.path.parent),
        acceleration_prefix=settings.resources.acceleration_prefix,
    )
    initial_resource_snapshot = resource_snapshots.initialize()
    resource_root = (
        initial_resource_snapshot.root
        if initial_resource_snapshot is not None
        else resource_cache_root
    )
    manifest_path = resource_root / "resource_manifest.json"
    if manifest_path.exists():
        ResourceManifest.load(
            manifest_path,
        ).validate_runtime_layout(resource_root)
    player_resources = (
        initial_resource_snapshot.player_resources
        if initial_resource_snapshot is not None
        else ResourceMap.from_root(resource_root)
    )
    encyclopedia_resources = (
        initial_resource_snapshot.encyclopedia_resources
        if initial_resource_snapshot is not None
        else EncyclopediaResourceStore.from_root(resource_root)
    )
    player_service = PlayerService(
        runtime_database,
        player_transport or DnaApiPlayerTransport(runtime_database),
        privacy_service,
        PlayerRenderer(runtime_database.path.parent / "rendered", player_resources),
        show_unowned_roles=settings.display.show_unowned_roles,
        resource_snapshots=resource_snapshots,
    )
    encyclopedia_service = EncyclopediaService(
        runtime_database,
        encyclopedia_transport
        or DnaApiEncyclopediaTransport(
            runtime_database,
            acceleration_prefix=settings.resources.acceleration_prefix,
        ),
        privacy_service,
        EncyclopediaRenderer(
            runtime_database.path.parent / "rendered", encyclopedia_resources
        ),
        encyclopedia_resources,
        guide_providers=tuple(settings.display.guide_providers),
        resource_snapshots=resource_snapshots,
    )
    subscriptions = SubscriptionStore(
        runtime_database.path.parent / "subscriptions.json"
    )
    deletion_coordinator = AccountDeletionCoordinator(runtime_database, subscriptions)
    membership_probe = AiocqhttpMembershipProbe(context=context)
    membership_service = MembershipService(
        runtime_database,
        subscriptions,
        membership_probe,
        deletion_coordinator=deletion_coordinator,
    )
    scheduler_registry = SchedulerRegistry(
        runtime_database.path.parent / "scheduler_state.json"
    )
    checkin_renderer = CheckinRenderer(
        runtime_database.path.parent / "rendered",
        encyclopedia_resources,
    )
    checkin_service = CheckinService(
        runtime_database,
        checkin_transport or DnaApiCheckinTransport(runtime_database),
        privacy_service,
        checkin_renderer,
        community_tasks=tuple(settings.sign_in.community_tasks),
        concurrency=settings.sign_in.concurrency,
        interval_range=settings.sign_in.concurrency_interval_seconds,
        subscriptions=subscriptions,
        resource_snapshots=resource_snapshots,
    )

    async def _push_sign(origin: str, text: str) -> None:
        msg = MessageChain(chain=[Plain(text)])
        try:
            res = context.send_message(origin, msg)
            if inspect.isawaitable(res):
                await res
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning(f"[dnaby][push_sign] 推送至 {origin} 失败: {error}")

    sign_scheduler = SignScheduler(
        checkin_service,
        subscriptions,
        sign_time=settings.sign_in.sign_time,
        scheduled_enabled=settings.sign_in.scheduled_enabled,
        enable_all_users=settings.sign_in.enable_all_users,
        push=_push_sign,
        registry=scheduler_registry,
    )
    notices_renderer = NoticesRenderer(
        runtime_database.path.parent / "rendered",
        encyclopedia_resources,
        simple_image=settings.notifications.secret_simple_image,
    )

    async def _push_notice(
        origin: str,
        payload: str | Path,
        at_user_id: str | list[str] | None = None,
    ) -> None:
        chain: list[Any] = []
        user_ids: list[str] = []
        if at_user_id:
            raw_ids = (
                [at_user_id] if isinstance(at_user_id, (str, int)) else list(at_user_id)
            )
            user_ids = [str(uid) for uid in raw_ids if uid]

        if isinstance(payload, Path) or (
            isinstance(payload, str)
            and (
                payload.endswith((".png", ".jpg", ".jpeg", ".webp"))
                or Path(payload).exists()
            )
        ):
            chain.append(AstrImage.fromFileSystem(str(payload)))
        else:
            text = str(payload).rstrip()
            if user_ids:
                text = f"{text}\n"
            chain.append(Plain(text))

        if user_ids:
            for idx, uid in enumerate(user_ids):
                if idx > 0:
                    chain.append(Plain(" "))
                chain.append(At(qq=str(uid)))

        msg = MessageChain(chain=chain)
        try:
            res = context.send_message(origin, msg)
            if inspect.isawaitable(res):
                await res
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning(f"[dnaby][push_notice] 推送至 {origin} 失败: {error}")

    notices_service = NoticesService(
        runtime_database,
        notices_transport or DnaApiNoticesTransport(runtime_database),
        privacy_service,
        notices_renderer,
        subscriptions=subscriptions,
        ann_state=AnnStateStore(runtime_database.path.parent / "ann_state.json"),
        secret_simple_image=settings.notifications.secret_simple_image,
        push=_push_notice,
        config_store=config if isinstance(config, dict) else None,
        resource_snapshots=resource_snapshots,
    )
    notices_scheduler = NoticesScheduler(
        notices_service,
        announcement_enabled=settings.notifications.announcement_enabled,
        push_time=settings.notifications.secret_push_time,
        poll_minutes=settings.notifications.announcement_check_minutes,
        registry=scheduler_registry,
    )
    admin_api_service = AdminApiService(
        scheduler_registry,
        subscriptions,
        {
            "dnaby_sign_daily": sign_scheduler,
            "dnaby_sign_cleanup": sign_scheduler,
            "dnaby_mh_push": notices_scheduler,
            "dnaby_ann_poll": notices_scheduler,
        },
        membership_service,
        config_store=config if isinstance(config, dict) else None,
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
        resource_snapshots=resource_snapshots,
    )

    def _synchronize_resources():
        return resource_snapshots.synchronize()

    resource_update_service = ResourceUpdateService(
        repo_root=Path(__file__).resolve().parents[2],
        rendered_root=runtime_database.path.parent / "rendered",
        synchronize=_synchronize_resources,
    )
    admin_panel_service = AdminPanelService(panel_service)
    admin_alias_service = AdminAliasService(
        resource_root=resource_root,
        custom_path=runtime_database.path.parent / "alias_custom.json",
    )
    admin_account_service = AdminAccountService(runtime_database)
    admin_preview_service = AdminPreviewService(
        runtime_database,
        player_service.transport,
        player_service.renderer,
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
        "membership_probe": membership_probe,
        "membership_service": membership_service,
        "deletion_coordinator": deletion_coordinator,
        "scheduler_registry": scheduler_registry,
        "sign_scheduler": sign_scheduler,
        "notices_service": notices_service,
        "notices_scheduler": notices_scheduler,
        "admin_api_service": admin_api_service,
        "admin_account_service": admin_account_service,
        "admin_preview_service": admin_preview_service,
        "admin_panel_service": admin_panel_service,
        "admin_alias_service": admin_alias_service,
        "panel_service": panel_service,
        "resource_update_service": resource_update_service,
        "resource_snapshots": resource_snapshots,
    }

    def _refresh_resource_views(snapshot: ResourceSnapshot) -> None:
        """在 generation 原子发布后替换所有只读资源视图。"""

        new_player_resources = snapshot.player_resources
        new_encyclopedia_resources = snapshot.encyclopedia_resources
        player_service.renderer.resources = new_player_resources
        encyclopedia_service.renderer.resources = new_encyclopedia_resources
        encyclopedia_service.resources = new_encyclopedia_resources
        checkin_renderer.resources = new_encyclopedia_resources
        notices_renderer.resources = new_encyclopedia_resources
        panel_service.resource_root = snapshot.root
        resolved_services["resource_root"] = snapshot.root
        resolved_services["player_resources"] = new_player_resources
        resolved_services["encyclopedia_resources"] = new_encyclopedia_resources

    resource_snapshots.subscribe(_refresh_resource_views)
    if services is not None:
        resolved_services.update(services)

    async def _sync_ann_config_on_startup() -> None:
        from .modules.notices import messages

        if subscriptions is None:
            return
        existing_subs = await subscriptions.get(messages.ANN_SUBSCRIBE)
        modified = False
        if isinstance(config, dict):
            notif = config.setdefault("notifications", {})
            if isinstance(notif, dict):
                groups = notif.setdefault("announcement_groups", {})
                if isinstance(groups, dict):
                    for sub in existing_subs:
                        if sub.group_id and str(sub.group_id) not in groups:
                            groups[str(sub.group_id)] = True
                            modified = True
            if modified:
                save_config = getattr(config, "save_config", None)
                if callable(save_config):
                    save_config()

        cfg_groups: object = settings.notifications.announcement_groups
        if cfg_groups:
            configured_ids: set[str] = set()
            if isinstance(cfg_groups, dict):
                configured_ids = {str(k) for k, v in cfg_groups.items() if v}
            elif isinstance(cfg_groups, list):
                configured_ids = {str(item) for item in cfg_groups}
            subscribed_ids = {str(s.group_id) for s in existing_subs if s.group_id}
            for gid in configured_ids - subscribed_ids:
                await subscriptions.add(
                    messages.ANN_SUBSCRIBE,
                    origin=f"group:{gid}",
                    user_id="",
                    bot_id="",
                    group_id=gid,
                    user_type="group",
                )

    web = WebRegistrar(context, build_admin_web_routes(resolved_services))
    lifecycle = PluginLifecycle(
        start_hooks=(
            web.initialize,
            _sync_ann_config_on_startup,
            sign_scheduler.start,
            notices_scheduler.start,
        ),
        # PluginLifecycle 会逆序执行 stop_hooks；先停 scheduler，再释放数据库。
        stop_hooks=(
            runtime_database.dispose,
            sign_scheduler.stop,
            notices_scheduler.stop,
        ),
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
            load_command_registry(prefixes=settings.display.command_prefixes)
            if command_registry is None or settings.display.command_prefixes != ["kk"]
            else command_registry
        ),
        settings=settings,
        services=resolved_services,
    )
