"""应用 runtime 组装入口。

``main.py`` 只负责 AstrBot ``Star`` 生命周期；所有入口扩展点在这里组装，
后续配置、持久化和业务模块按阶段加入，不让入口文件重新膨胀。
"""

from __future__ import annotations

import asyncio
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
from .infrastructure.data_layout import RuntimeDataLayout
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
from .infrastructure.legacy_layout import LegacyLayoutDetector
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
    AssetResolver,
    EncyclopediaResourceStore,
    ResourceGenerationError,
    ResourceSnapshot,
    ResourceSnapshotCoordinator,
)
from .infrastructure.resources.paths import PLUGIN_NAME
from .infrastructure.scheduler import SignPushPayload, SignScheduler
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
from .modules.notices.mh_cache import MH_CACHE_TYPE
from .modules.notices.service import NoticesService
from .modules.notices.target_service import AnnouncementTargetService
from .modules.operations.resource_service import ResourceUpdateService
from .modules.player.cache import (
    PLAYER_CARD_CACHE_TYPE,
    PLAYER_DATA_CACHE_TYPE,
    PlayerCache,
)
from .modules.player.contracts import PlayerTransport
from .modules.player.service import PlayerService
from .modules.privacy import PrivacyService
from .utils.image_utils import ImageFetcher
from .utils.name_convert import configure_alias_storage

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

    runtime_data_layout: RuntimeDataLayout | None = None
    if database is None:
        from astrbot.api.star import StarTools

        runtime_data_layout = RuntimeDataLayout.from_data_dir(
            StarTools.get_data_dir(PLUGIN_NAME),
        )
        # 必须先完成只读旧布局检测，再进入任何会创建数据库或运行期目录的阶段。
        LegacyLayoutDetector(runtime_data_layout).ensure_compatible()

    # 在构造 runtime 前校验运行期用户文案，避免插件已加载后才暴露目录问题。
    validate_tip_catalog()
    settings = DnabySettings.from_config(config)
    from .utils import dna_api, image_utils

    if services is not None and "image_fetcher" in services:
        image_fetcher = cast(ImageFetcher, services["image_fetcher"])
    else:
        # runtime 必须拥有自己的 client，避免重载或测试切换事件循环后复用旧连接池。
        image_fetcher = ImageFetcher()
    image_utils.set_default_image_fetcher(image_fetcher)

    dna_api.configure_network(
        api_base_url=settings.network.api_base_url,
        proxy_url=settings.network.proxy_url,
        websocket_continue_seconds=settings.network.websocket_continue_seconds,
        websocket_wait_seconds=settings.network.websocket_wait_seconds,
    )
    request_gate = RequestConcurrencyGate(settings.network.max_concurrent_requests)
    runtime_database = database
    if runtime_database is None:
        if runtime_data_layout is None:
            raise RuntimeError("运行期数据布局尚未解析")
        runtime_database = AsyncDatabase.from_data_dir(runtime_data_layout.data_dir)
    if runtime_data_layout is None:
        runtime_data_layout = RuntimeDataLayout.from_data_dir(
            runtime_database.path.parent,
        )
    configure_alias_storage(runtime_data_layout)
    resolved_account_transport = account_transport or DnaApiAccountTransport()
    account_service = AccountService(
        runtime_database,
        resolved_account_transport,
        max_bind_count=settings.login.max_bind_count,
        default_auto_sign_enabled=settings.sign_in.default_auto_sign_enabled,
    )
    if services is not None and "account_service" in services:
        account_service = cast(AccountService, services["account_service"])

    custom_alias_path = runtime_data_layout.char_alias_path
    custom_weapon_alias_path = runtime_data_layout.weapon_alias_path
    resource_repository_root = runtime_data_layout.resource_repository_dir
    resource_generations_root = runtime_data_layout.resource_generations_dir
    resource_snapshots = ResourceSnapshotCoordinator(
        resource_repository_root,
        generations_root=resource_generations_root,
        acceleration_prefix=settings.resources.acceleration_prefix,
        custom_alias_path=custom_alias_path,
        custom_weapon_alias_path=custom_weapon_alias_path,
    )
    asset_resolver = AssetResolver(
        coordinator=resource_snapshots,
        dynamic_root=runtime_data_layout.cache_assets_dir,
        downloader=image_fetcher,
    )
    if services is not None and "asset_resolver" in services:
        asset_resolver = cast(AssetResolver, services["asset_resolver"])

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
            resource_snapshots=resource_snapshots,
        )
    set_login_flow = getattr(account_service, "set_login_flow", None)
    if callable(set_login_flow):
        set_login_flow(login_flow)
    privacy_service = PrivacyService(
        runtime_database,
        allow_mention_query=settings.display.allow_mention_query,
    )
    # 构造期只接纳已由外部显式注入的 verified snapshot；重载时的 current
    # 指针和完整资源校验延后到异步生命周期，避免阻塞 AstrBot 插件加载线程。
    # 没有已验证快照时使用显式空视图，直到异步校验成功后由监听器刷新。
    initial_resource_snapshot = resource_snapshots.current_snapshot
    resource_root = (
        initial_resource_snapshot.root
        if initial_resource_snapshot is not None
        else None
    )
    player_resources = (
        initial_resource_snapshot.player_resources
        if initial_resource_snapshot is not None
        else ResourceMap()
    )
    encyclopedia_resources = (
        initial_resource_snapshot.encyclopedia_resources
        if initial_resource_snapshot is not None
        else EncyclopediaResourceStore()
    )
    rendered_root = runtime_data_layout.cache_rendered_dir
    cache_manager = CacheManager(
        runtime_data_layout.cache_dir,
        settings.cache,
        cache_type_roots={
            PLAYER_DATA_CACHE_TYPE: runtime_data_layout.cache_api_dir,
            PLAYER_CARD_CACHE_TYPE: runtime_data_layout.cache_rendered_dir,
            MH_CACHE_TYPE: runtime_data_layout.cache_api_dir,
            "announcement": runtime_data_layout.cache_media_dir,
        },
    )
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
        PlayerRenderer(rendered_root, player_resources, asset_resolver=asset_resolver),
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
        rendered_root=rendered_root,
    )
    subscriptions = SubscriptionStore(runtime_data_layout.subscriptions_path)
    deletion_coordinator = AccountDeletionCoordinator(runtime_database, subscriptions)
    membership_probe = AiocqhttpMembershipProbe(context=context)
    membership_service = MembershipService(
        runtime_database,
        subscriptions,
        membership_probe,
        deletion_coordinator=deletion_coordinator,
    )
    scheduler_registry = SchedulerRegistry(runtime_data_layout.scheduler_state_path)
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
        group_report=settings.sign_in.group_report,
        group_report_image=settings.sign_in.group_report_image,
    )

    async def _push_sign(origin: str, payload: SignPushPayload) -> None:
        chain: list[Any] = []
        if payload.image_bytes is not None:
            chain.append(AstrImage.fromBytes(payload.image_bytes))
        else:
            chain.append(Plain(payload.text))
        if payload.detail_text:
            chain.append(Plain(f"\n{payload.detail_text}"))
        for user_id, detail in payload.mention_details:
            chain.append(Plain("\n"))
            chain.append(At(qq=str(user_id)))
            if detail:
                chain.append(Plain(detail))
        msg = MessageChain(chain=chain)
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
        sign_task_enabled=settings.sign_in.scheduler_enabled_for_runtime,
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
    ann_state = AnnStateStore(runtime_data_layout.ann_state_path)
    ann_delivery_state = AnnDeliveryStateStore(
        runtime_data_layout.ann_delivery_state_path,
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

        nodes = [Node(content=[Plain(text)], name="DNA", uin="0") for text in texts]
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
        runtime_data_layout.client_update_state_path,
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
        target_ids=tuple(settings.client_updates.targets),
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
        resource_root=resource_repository_root,
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

        current_root = resolved_services.get("resource_root")
        if current_root is None:
            updated = EncyclopediaResourceStore()
        else:
            updated = EncyclopediaResourceStore.from_root(
                Path(current_root),
                custom_alias_path=custom_alias_path,
                custom_weapon_alias_path=custom_weapon_alias_path,
            )
        encyclopedia_service.renderer.resources = updated
        encyclopedia_service.resources = updated
        checkin_renderer.resources = updated
        notices_renderer.resources = updated
        resolved_services["encyclopedia_resources"] = updated

    alias_root = resource_root or resource_generations_root / ".unavailable"
    admin_alias_service = AdminAliasService(
        default_alias_path=alias_root / "alias" / "char_alias.json",
        weapon_alias_path=alias_root / "alias" / "weapon_alias.json",
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
        "asset_resolver": asset_resolver,
        "image_fetcher": image_fetcher,
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
        admin_alias_service.default_alias_path = (
            snapshot.root / "alias" / "char_alias.json"
        )
        admin_alias_service.weapon_alias_path = (
            snapshot.root / "alias" / "weapon_alias.json"
        )
        resolved_services["resource_root"] = snapshot.root
        resolved_services["player_resources"] = new_player_resources
        resolved_services["encyclopedia_resources"] = new_encyclopedia_resources

    resource_snapshots.subscribe(_refresh_resource_views)

    async def _initialize_resource_views() -> None:
        """在异步生命周期中完成完整资源校验，避免阻塞插件构造线程。"""

        try:
            snapshot = await asyncio.to_thread(resource_snapshots.validate_current)
        except ResourceGenerationError as error:
            resource_snapshots.record_validation_failure(error)
            from astrbot.api import logger

            logger.warning(
                "[dnaby][resources] 当前 generation 校验失败，资源暂不可用；"
                "可执行同步资源修复（%s）",
                type(error).__name__,
            )
            return
        if snapshot is not None:
            _refresh_resource_views(snapshot)

    async def _stop_resource_views() -> None:
        """资源校验不持有后台任务，但需要与启动 hook 保持索引对齐。"""

    async def _stop_image_fetcher() -> None:
        """下载器在 finalizer 阶段关闭；此 hook 只保持生命周期索引对齐。"""

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
            image_fetcher.start,
            _initialize_resource_views,
            login_flow.start,
            client_update_service.initialize,
            web.initialize,
            cache_maintenance.start,
            sign_scheduler.start,
            notices_scheduler.start,
            client_updates_scheduler.start,
            agent_tools_lifecycle.start,
        ),
        # PluginLifecycle 会逆序执行，先取消 scheduler/监听任务，
        # 再运行 transport 和数据库 finalizer。
        stop_hooks=(
            _stop_image_fetcher,
            _stop_resource_views,
            login_flow.stop,
            web.stop,
            cache_maintenance.stop,
            sign_scheduler.stop,
            notices_scheduler.stop,
            client_updates_scheduler.stop,
            agent_tools_lifecycle.stop,
        ),
        finalizer_hooks=(
            image_fetcher.close,
            resource_update_service.stop,
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
            if command_registry is None or settings.display.command_prefixes != ["dna"]
            else command_registry
        ),
        settings=settings,
        services=resolved_services,
    )
