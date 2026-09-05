"""应用 runtime 组装入口。

``main.py`` 只负责 AstrBot ``Star`` 生命周期；所有入口扩展点在这里组装，
后续配置、持久化和业务模块按阶段加入，不让入口文件重新膨胀。
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from astrbot.api.star import Context
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import At, Node, Nodes, Plain
from astrbot.core.message.components import Image as AstrImage
from astrbot.core.message.message_event_result import MessageChain

from .entry.admin_web import build_admin_web_routes
from .entry.agent_tools import AgentToolsLifecycle
from .entry.commands import CommandRegistry, load_command_registry
from .entry.event import EmptyEventEntryPoint, EventEntryPoint
from .entry.lifecycle import PluginLifecycle
from .entry.response import ResponseFactory
from .entry.web import WebRegistrar
from .infrastructure.cache import CacheMaintenance, CacheManager
from .infrastructure.client_updates_scheduler import ClientUpdatesScheduler
from .infrastructure.config import DnabySettings
from .infrastructure.http import (
    ClientUpdateTransport as DnaApiClientUpdateTransport,
)
from .infrastructure.http import (
    DnaApiAccountTransport,
    DnaApiCheckinTransport,
    DnaApiEncyclopediaTransport,
    DnaApiNoticesTransport,
    DnaApiPlayerTransport,
    RequestConcurrencyGate,
)
from .infrastructure.i18n import validate_tip_catalog
from .infrastructure.notices_scheduler import NoticesScheduler
from .infrastructure.persistence import AsyncDatabase
from .infrastructure.rendering import (
    DEFAULT_RENDERED_RETENTION_SECONDS,
    CheckinRenderer,
    EncyclopediaRenderer,
    NoticesRenderer,
    PlayerRenderer,
    RenderedFileStore,
    ResourceMap,
)
from .infrastructure.resources import (
    EncyclopediaResourceStore,
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
from .modules.account.login_flow import LoginFlowCoordinator
from .modules.account.transport import LoginTransport, build_transport
from .modules.admin import (
    AccountDeletionCoordinator,
    AdminAccountService,
    AdminAliasService,
    AdminApiService,
    AdminPreviewService,
    AiocqhttpMembershipProbe,
    MembershipService,
)
from .modules.checkin.contracts import CheckinTransport
from .modules.checkin.service import CheckinService
from .modules.client_updates.contracts import ClientUpdateTransport
from .modules.client_updates.delivery import (
    ClientUpdateDeliveryService,
    ClientUpdatePushAdapter,
)
from .modules.client_updates.service import ClientUpdateService
from .modules.client_updates.state import ClientUpdateStateStore
from .modules.encyclopedia.contracts import EncyclopediaTransport
from .modules.encyclopedia.service import EncyclopediaService
from .modules.notices.ann_delivery_state import AnnDeliveryStateStore
from .modules.notices.ann_state import AnnStateStore
from .modules.notices.contracts import NoticesTransport
from .modules.notices.service import NoticesService
from .modules.notices.target_service import AnnouncementTargetService
from .modules.operations.resource_service import ResourceUpdateService
from .modules.player.cache import PlayerCache
from .modules.player.contracts import PlayerTransport
from .modules.player.service import PlayerService
from .modules.privacy import PrivacyService

PluginConfig = AstrBotConfig | dict[str, Any] | None


def _cache_maintenance_interval(settings: DnabySettings) -> float:
    """返回缓存维护周期；禁用/永久模式仍维护 rendered 临时文件。"""

    if settings.cache.ttl_hours > 0:
        return float(settings.cache.ttl_hours * 60 * 60)
    return float(DEFAULT_RENDERED_RETENTION_SECONDS)


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
    client_updates_transport: ClientUpdateTransport | None = None,
    services: Mapping[str, object] | None = None,
    plugin_context: object | None = None,
) -> PluginRuntime:
    """为一个 AstrBot 插件实例组装代码 registry 和 typed services。"""

    # 在构造 runtime 前校验运行期用户文案，避免插件已加载后才暴露目录问题。
    validate_tip_catalog()
    settings = DnabySettings.from_config(config)
    from .utils import dna_api

    dna_api.configure_network(
        api_base_url=settings.network.api_base_url,
        proxy_url=settings.network.proxy_url,
        websocket_continue_seconds=settings.network.websocket_continue_seconds,
        websocket_wait_seconds=settings.network.websocket_wait_seconds,
    )
    request_gate = RequestConcurrencyGate(settings.network.max_concurrent_requests)
    runtime_database = database
    if runtime_database is None:
        from astrbot.api.star import StarTools

        runtime_database = AsyncDatabase.from_data_dir(
            StarTools.get_data_dir(PLUGIN_NAME),
        )
    resolved_account_transport = account_transport or DnaApiAccountTransport()
    account_service = AccountService(
        runtime_database,
        resolved_account_transport,
        max_bind_count=settings.login.max_bind_count,
        default_auto_sign_enabled=settings.sign_in.default_auto_sign_enabled,
    )
    if services is not None and "account_service" in services:
        account_service = cast(AccountService, services["account_service"])

    async def _notify_login(actor: Any, response: object) -> None:
        """把后台登录终态投递回发起登录的 AstrBot 会话。"""

        origin = getattr(actor, "unified_msg_origin", None)
        text = getattr(response, "text", None)
        if not isinstance(origin, str) or not origin or not isinstance(text, str):
            return
        try:
            message = MessageChain(chain=[Plain(text)])
            result = context.send_message(origin, message)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.error(
                "登录完成消息发送失败 kind=%s",
                type(error).__name__,
            )

    login_flow: object
    if services is not None and "login_flow" in services:
        login_flow = services["login_flow"]
    else:
        external_login_transport: LoginTransport | None = None
        if settings.login.transport != "local" and settings.login.url.strip():
            external_login_transport = build_transport(
                settings.login.url,
                settings.login.transport,
                settings.login.shared_secret.get_secret_value(),
            )
        injected_login_server = (
            cast(Any, services["login_server"])
            if services is not None and "login_server" in services
            else None
        )
        login_flow = LoginFlowCoordinator(
            account_service,
            settings.login,
            account_transport=resolved_account_transport,
            external_transport=external_login_transport,
            local_server=injected_login_server,
            notify=_notify_login,
        )
    set_login_flow = getattr(account_service, "set_login_flow", None)
    if callable(set_login_flow):
        set_login_flow(login_flow)
    privacy_service = PrivacyService(
        runtime_database,
        allow_mention_query=settings.display.allow_mention_query,
    )
    custom_alias_path = runtime_database.path.parent / "alias_custom.json"
    custom_weapon_alias_path = runtime_database.path.parent / "weapon_alias_custom.json"
    resource_cache_root = resource_repository_dir(runtime_database.path.parent)
    resource_snapshots = ResourceSnapshotCoordinator(
        resource_cache_root,
        generations_root=resource_generations_dir(runtime_database.path.parent),
        acceleration_prefix=settings.resources.acceleration_prefix,
        custom_alias_path=custom_alias_path,
        custom_weapon_alias_path=custom_weapon_alias_path,
    )
    # 启动阶段只读取 current 指针和已发布 generation 的轻量 metadata；
    # 完整校验和 Git 同步仅允许由显式资源同步路径触发，避免构造 runtime 时做重型 I/O。
    initial_resource_snapshot = resource_snapshots.load_current()
    resource_root = (
        initial_resource_snapshot.root
        if initial_resource_snapshot is not None
        else resource_cache_root
    )
    player_resources = (
        initial_resource_snapshot.player_resources
        if initial_resource_snapshot is not None
        else ResourceMap.from_root(resource_root)
    )
    encyclopedia_resources = (
        initial_resource_snapshot.encyclopedia_resources
        if initial_resource_snapshot is not None
        else EncyclopediaResourceStore.from_root(
            resource_root,
            custom_alias_path=custom_alias_path,
            custom_weapon_alias_path=custom_weapon_alias_path,
        )
    )
    rendered_root = runtime_database.path.parent / "rendered"
    cache_manager = CacheManager(runtime_database.path.parent / "cache", settings.cache)
    player_cache = PlayerCache(
        cache_manager,
        rendered_root,
    )
    rendered_store = RenderedFileStore(
        rendered_root,
        retention_seconds=DEFAULT_RENDERED_RETENTION_SECONDS,
    )
    cache_maintenance = CacheMaintenance(
        cache_manager,
        rendered_store,
        interval_seconds=_cache_maintenance_interval(settings),
    )
    if services is not None:
        if "request_gate" in services:
            request_gate = cast(RequestConcurrencyGate, services["request_gate"])
        if "cache_manager" in services:
            cache_manager = cast(CacheManager, services["cache_manager"])
        if "player_cache" in services:
            player_cache = cast(PlayerCache, services["player_cache"])
            if "cache_manager" not in services:
                cache_manager = player_cache.manager
        elif "cache_manager" in services:
            player_cache = PlayerCache(
                cache_manager,
                rendered_root,
            )
        if "rendered_store" in services:
            rendered_store = cast(RenderedFileStore, services["rendered_store"])
        if "cache_maintenance" in services:
            cache_maintenance = cast(
                CacheMaintenance,
                services["cache_maintenance"],
            )
        elif (
            "cache_manager" in services
            or "player_cache" in services
            or "rendered_store" in services
        ):
            cache_maintenance = CacheMaintenance(
                cache_manager,
                rendered_store,
                interval_seconds=_cache_maintenance_interval(settings),
            )
    player_service = PlayerService(
        runtime_database,
        player_transport
        or DnaApiPlayerTransport(runtime_database, request_gate=request_gate),
        privacy_service,
        PlayerRenderer(rendered_root, player_resources),
        show_unowned_roles=settings.display.show_unowned_roles,
        resource_snapshots=resource_snapshots,
        cache=player_cache,
        refresh_send_card=settings.cache.refresh_send_card,
    )
    encyclopedia_service = EncyclopediaService(
        runtime_database,
        encyclopedia_transport
        or DnaApiEncyclopediaTransport(
            runtime_database,
            acceleration_prefix=settings.resources.acceleration_prefix,
            request_gate=request_gate,
        ),
        privacy_service,
        EncyclopediaRenderer(rendered_root, encyclopedia_resources),
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
        rendered_root,
        encyclopedia_resources,
    )
    checkin_service = CheckinService(
        runtime_database,
        checkin_transport
        or DnaApiCheckinTransport(runtime_database, request_gate=request_gate),
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
        push=_push_sign,
        registry=scheduler_registry,
    )
    notices_renderer = NoticesRenderer(
        rendered_root,
        encyclopedia_resources,
        simple_image=settings.notifications.secret_simple_image,
        cache_manager=cache_manager,
        request_gate=request_gate,
    )

    async def _push_notice(
        origin: str,
        payload: str | Path | tuple[Path, ...],
        at_user_id: str | list[str] | None = None,
    ) -> bool:
        chain: list[Any] = []
        user_ids: list[str] = []
        if at_user_id:
            raw_ids = (
                [at_user_id] if isinstance(at_user_id, (str, int)) else list(at_user_id)
            )
            user_ids = [str(uid) for uid in raw_ids if uid]

        if isinstance(payload, tuple):
            for image_path in payload:
                chain.append(AstrImage.fromFileSystem(str(image_path)))
        elif isinstance(payload, Path) or (
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
                res = await res
            return res is not False
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning(
                f"[dnaby][push_notice] 推送至 {origin} 失败: {type(error).__name__}",
            )
            return False

    resolved_notices_transport = notices_transport or DnaApiNoticesTransport(
        runtime_database,
        request_gate=request_gate,
    )
    ann_state = AnnStateStore(runtime_database.path.parent / "ann_state.json")
    ann_delivery_state = AnnDeliveryStateStore(
        runtime_database.path.parent / "ann_delivery_state.json",
    )

    class _AnnouncementListSource:
        async def current_announcement_ids(self) -> tuple[str, ...]:
            snapshot = await resolved_notices_transport.get_ann_list()
            return tuple(
                post.post_id for post in snapshot.posts if post.post_id.isdigit()
            )

    announcement_targets = AnnouncementTargetService(
        subscriptions,
        ann_delivery_state,
        _AnnouncementListSource(),
    )
    notices_service = NoticesService(
        runtime_database,
        resolved_notices_transport,
        privacy_service,
        notices_renderer,
        subscriptions=subscriptions,
        ann_state=ann_state,
        ann_delivery_state=ann_delivery_state,
        secret_simple_image=settings.notifications.secret_simple_image,
        cache_manager=cache_manager,
        push=_push_notice,
        resource_snapshots=resource_snapshots,
        request_gate=request_gate,
        announcement_targets=announcement_targets,
        secret_retry_interval_seconds=settings.notifications.secret_retry_interval_seconds,
    )
    notices_scheduler = NoticesScheduler(
        notices_service,
        announcement_enabled=settings.notifications.announcement_enabled,
        poll_minutes=settings.notifications.announcement_check_minutes,
        push_minute=settings.notifications.secret_push_minute,
        registry=scheduler_registry,
    )

    async def _send_client_update_text(origin: str, text: str) -> bool:
        """把客户端更新普通文本交给 AstrBot 主动消息接口。"""

        try:
            result = context.send_message(origin, MessageChain(chain=[Plain(text)]))
            if inspect.isawaitable(result):
                result = await result
            return result is not False
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning(
                "[dnaby][client_update] 普通消息推送失败（错误类型：%s）",
                type(error).__name__,
            )
            return False

    async def _send_client_update_forward(
        origin: str,
        texts: tuple[str, ...],
    ) -> bool:
        """使用 AstrBot 原生 Nodes 组件尝试 OneBot 合并转发。"""

        nodes = [Node(content=[Plain(text)], name="DNAUID", uin="0") for text in texts]
        try:
            result = context.send_message(
                origin,
                MessageChain(chain=[Nodes(nodes)]),
            )
            if inspect.isawaitable(result):
                result = await result
            return result is not False
        except Exception as error:  # noqa: BLE001
            from astrbot.api import logger

            logger.warning(
                "[dnaby][client_update] 合并转发推送失败（错误类型：%s）",
                type(error).__name__,
            )
            return False

    resolved_client_updates_transport = (
        client_updates_transport
        or DnaApiClientUpdateTransport(
            request_gate=request_gate,
        )
    )
    if services is not None and "client_updates_transport" in services:
        resolved_client_updates_transport = cast(
            ClientUpdateTransport,
            services["client_updates_transport"],
        )
    client_update_state = ClientUpdateStateStore(
        runtime_database.path.parent / "client_update_state.json",
    )
    if services is not None and "client_update_state" in services:
        client_update_state = cast(
            ClientUpdateStateStore,
            services["client_update_state"],
        )
    client_update_service = ClientUpdateService(
        client_update_state,
        transport=resolved_client_updates_transport,
        subscriptions=subscriptions,
        channels=tuple(settings.client_updates.channels),
    )
    if services is not None and "client_update_service" in services:
        client_update_service = cast(
            ClientUpdateService,
            services["client_update_service"],
        )
    client_update_push_adapter = ClientUpdatePushAdapter(
        send_text=_send_client_update_text,
        send_forward=_send_client_update_forward,
        merge_forward=settings.client_updates.merge_forward,
    )
    if services is not None and "client_update_push_adapter" in services:
        client_update_push_adapter = cast(
            ClientUpdatePushAdapter,
            services["client_update_push_adapter"],
        )
    client_update_delivery = ClientUpdateDeliveryService(
        subscriptions,
        client_update_push_adapter,
        state=client_update_state,
    )
    if services is not None and "client_update_delivery" in services:
        client_update_delivery = cast(
            ClientUpdateDeliveryService,
            services["client_update_delivery"],
        )
    client_updates_scheduler = ClientUpdatesScheduler(
        client_update_service,
        client_update_delivery,
        enabled=settings.client_updates.enabled,
        check_minutes=settings.client_updates.check_minutes,
        registry=scheduler_registry,
    )
    if services is not None and "client_updates_scheduler" in services:
        client_updates_scheduler = cast(
            ClientUpdatesScheduler,
            services["client_updates_scheduler"],
        )

    admin_api_service = AdminApiService(
        scheduler_registry,
        subscriptions,
        {
            "dnaby_sign_daily": sign_scheduler,
            "dnaby_sign_cleanup": sign_scheduler,
            "dnaby_mh_push": notices_scheduler,
            "dnaby_ann_poll": notices_scheduler,
            "dnaby_client_update_poll": client_updates_scheduler,
        },
        membership_service,
        config_store=config if isinstance(config, dict) else None,
        announcement_target_service=announcement_targets,
    )

    def _synchronize_resources():
        return resource_snapshots.synchronize()

    resource_update_service = ResourceUpdateService(
        synchronize=_synchronize_resources,
        resource_root=resource_root,
        resource_snapshots=resource_snapshots,
    )
    if services is not None and "resource_update_service" in services:
        # 复用现有 services 注入边界，使生命周期测试和宿主可提供同契约实现。
        resource_update_service = cast(
            ResourceUpdateService,
            services["resource_update_service"],
        )

    def _refresh_alias_views() -> None:
        """别名写入后立即替换当前百科视图，不要求重载插件。"""

        current_root = Path(resolved_services.get("resource_root", resource_root))
        updated = EncyclopediaResourceStore.from_root(
            current_root,
            custom_alias_path=custom_alias_path,
            custom_weapon_alias_path=custom_weapon_alias_path,
        )
        encyclopedia_service.renderer.resources = updated
        encyclopedia_service.resources = updated
        checkin_renderer.resources = updated
        notices_renderer.resources = updated
        resolved_services["encyclopedia_resources"] = updated

    admin_alias_service = AdminAliasService(
        resource_root=resource_root,
        custom_path=custom_alias_path,
        weapon_custom_path=custom_weapon_alias_path,
        refresh=_refresh_alias_views,
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
        "login_flow": login_flow,
        "privacy_service": privacy_service,
        "cache_manager": cache_manager,
        "player_cache": player_cache,
        "player_service": player_service,
        "resource_root": resource_root,
        "rendered_root": rendered_root,
        "rendered_store": rendered_store,
        "request_gate": request_gate,
        "cache_maintenance": cache_maintenance,
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
        "announcement_target_service": announcement_targets,
        "notices_scheduler": notices_scheduler,
        "client_updates_transport": resolved_client_updates_transport,
        "client_update_state": client_update_state,
        "client_update_service": client_update_service,
        "client_update_push_adapter": client_update_push_adapter,
        "client_update_delivery": client_update_delivery,
        "client_updates_scheduler": client_updates_scheduler,
        "admin_api_service": admin_api_service,
        "admin_account_service": admin_account_service,
        "admin_preview_service": admin_preview_service,
        "admin_alias_service": admin_alias_service,
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
        resolved_services["resource_root"] = snapshot.root
        resolved_services["player_resources"] = new_player_resources
        resolved_services["encyclopedia_resources"] = new_encyclopedia_resources

    resource_snapshots.subscribe(_refresh_resource_views)
    if services is not None:
        resolved_services.update(services)

    agent_tools_lifecycle = AgentToolsLifecycle(
        context=context,
        enabled=settings.agent_tools.enabled,
        services=resolved_services,
        command_prefixes=tuple(settings.display.command_prefixes),
        plugin_context=plugin_context,
    )
    resolved_services["agent_tools_lifecycle"] = agent_tools_lifecycle

    def _warn_deprecated_announcement_config() -> None:
        """旧公告群组配置不再参与运行，只给出不泄露值的迁移提示。"""

        if not isinstance(config, dict):
            return
        notifications = config.get("notifications")
        if isinstance(notifications, dict) and "announcement_groups" in notifications:
            from astrbot.api import logger

            logger.warning(
                "[dnaby] notifications.announcement_groups 已弃用；公告目标请在真实群聊中重新执行订阅命令。"
            )

    _warn_deprecated_announcement_config()

    web = WebRegistrar(
        context,
        build_admin_web_routes(resolved_services),
        plugin_name=PLUGIN_NAME,
    )
    lifecycle = PluginLifecycle(
        start_hooks=(
            login_flow.start,
            web.initialize,
            cache_maintenance.start,
            sign_scheduler.start,
            notices_scheduler.start,
            client_updates_scheduler.start,
            agent_tools_lifecycle.start,
        ),
        # stop_hooks 与 start_hooks 按阶段对齐；PluginLifecycle 会逆序执行，
        # 先取消 scheduler/监听任务，再运行 transport 和数据库 finalizer。
        stop_hooks=(
            login_flow.stop,
            web.stop,
            cache_maintenance.stop,
            sign_scheduler.stop,
            notices_scheduler.stop,
            client_updates_scheduler.stop,
            agent_tools_lifecycle.stop,
        ),
        finalizer_hooks=(
            dna_api.close,
            runtime_database.dispose,
        ),
    )
    return PluginRuntime(
        context=context,
        config=config,
        lifecycle=lifecycle,
        events=EmptyEventEntryPoint(),
        responses=ResponseFactory(
            temporary_roots=(rendered_root,),
            rendered_store=rendered_store,
        ),
        commands=(
            load_command_registry(prefixes=settings.display.command_prefixes)
            if command_registry is None or settings.display.command_prefixes != ["kk"]
            else command_registry
        ),
        settings=settings,
        services=resolved_services,
    )
