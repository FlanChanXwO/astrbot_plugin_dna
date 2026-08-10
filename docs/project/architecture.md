# 架构

- 入口：`main.py`（Star 子类，`@filter.regex` 主门 + 分发；`initialize()/terminate()` 编排 DB/定时任务/Web API）。
- 命令：`commands.json` → 分发表 → `dnaby/dna_*/` 处理器（`async def handle_*(sender, ctx)`）。
- 发送：`dnaby/session.py`（`EventContext` + `Sender`）→ handler `yield event.*_result`。
- 配置：`dnaby/dna_config/` 定义 → 生成 `_conf_schema.json` → `AstrBotConfig`。
- 数据：`dnaby/utils/database/`（SQLModel 5 表，私有 aiosqlite engine）。
- 订阅/推送：`dnaby/utils/subscriptions.py`。
- 登录：`dnaby/dna_user/`（`login_router.py` 等）+ `register_web_api`。

详见 [design.md](../porting/design.md) 的映射表。
