"""AstrBot Plugin — astrbot_plugin_dnaby 入口。

- 聚合各命令为单个 ``@filter.regex`` 主门，分发到业务处理器。
- ``initialize()``：初始化 DB / 配置 / 订阅存储 / Web API / 定时任务。
- 业务编排不写在此文件，见 ``dnaby/*``。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig

if __package__:
    # AstrBot 以 ``data.plugins.<plugin>.main`` 加载入口时，业务包必须走包内相对导入。
    from .dnaby.dispatch import MASTER_PATTERN, build_context, dispatch
    from .dnaby.dna_config import DNAConfig, DNASignConfig, bind_core_config
    from .dnaby.dna_user.local_server import LocalLoginServer
    from .dnaby.scheduler import start_scheduled_tasks
    from .dnaby.utils.database.base import close_db, create_db_and_tables, init_db
    from .dnaby.utils.resource.RESOURCE_PATH import MAIN_PATH
    from .dnaby.utils.session import Sender
    from .dnaby.utils.subscriptions import bind_push, gs_subscribe
else:
    # 允许在插件目录直接 ``import main``，便于本地测试与工具检查。
    from dnaby.dispatch import MASTER_PATTERN, build_context, dispatch
    from dnaby.dna_config import DNAConfig, DNASignConfig, bind_core_config
    from dnaby.dna_user.local_server import LocalLoginServer
    from dnaby.scheduler import start_scheduled_tasks
    from dnaby.utils.database.base import close_db, create_db_and_tables, init_db
    from dnaby.utils.resource.RESOURCE_PATH import MAIN_PATH
    from dnaby.utils.session import Sender
    from dnaby.utils.subscriptions import bind_push, gs_subscribe


class DnabyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context, config)
        self.context = context
        self.config = config
        self._tasks: list = []
        self._login_server: LocalLoginServer | None = None

    async def initialize(self) -> None:
        # 数据库
        init_db(MAIN_PATH / "dnaby.db")
        await create_db_and_tables()
        # 配置（AstrBotConfig 后端）
        DNAConfig.bind(self.config)
        DNASignConfig.bind(self.config)
        bind_core_config(self.context.get_config())
        # 订阅存储 + 推送
        await gs_subscribe.init(MAIN_PATH / "subscriptions.json")
        bind_push(lambda umo, chain: self.context.send_message(umo, chain))
        # Web API（登录页/发码）
        self._register_web_apis()
        await self._start_local_login_server()
        # 定时任务（签到/密函/公告轮询）
        self._tasks = await start_scheduled_tasks()
        logger.info("[dnaby] 初始化完成，命令已注册。")

    async def terminate(self) -> None:
        await self._stop_local_login_server()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await close_db()
        logger.info("[dnaby] 已卸载。")

    def _register_web_apis(self) -> None:
        try:
            if __package__:
                from .dnaby.dna_user.login_router import get_routes
            else:
                from dnaby.dna_user.login_router import get_routes

            for route, handler, methods, desc in get_routes():
                self.context.register_web_api(route, handler, methods, desc)
        except Exception:
            logger.exception("[dnaby] 登录 Web API 注册失败")
            raise

    async def _start_local_login_server(self) -> None:
        transport_name = DNAConfig.get_config("DNALoginTransport").data.strip()
        if transport_name not in {"", "local"}:
            return

        if __package__:
            from .dnaby.dna_user.login_router import bind_local_login_server, get_routes
        else:
            from dnaby.dna_user.login_router import bind_local_login_server, get_routes

        bind_host = str(DNAConfig.get_config("DNALoginBindHost").data).strip()
        port = int(DNAConfig.get_config("DNALoginPort").data)
        server = LocalLoginServer(
            get_routes(),
            host=bind_host,
            port=port,
        )
        await server.start()
        bind_local_login_server(server)
        self._login_server = server
        logger.info("[dnaby] 本地登录服务已启动: %s", server.base_url)

    async def _stop_local_login_server(self) -> None:
        if __package__:
            from .dnaby.dna_user.login_router import bind_local_login_server
        else:
            from dnaby.dna_user.login_router import bind_local_login_server

        bind_local_login_server(None)
        server, self._login_server = self._login_server, None
        if server is not None:
            await server.stop()

    @filter.regex(MASTER_PATTERN)
    async def regex_command(self, event: AstrMessageEvent):
        ctx = build_context(event)

        async def send_now(chain: list) -> None:
            await self.context.send_message(ctx.unified_msg_origin, MessageChain(chain))

        sender = Sender(ctx, immediate_send=send_now)
        await dispatch(event, sender, ctx)
        for chain in sender.to_chains():
            yield event.chain_result(chain)
