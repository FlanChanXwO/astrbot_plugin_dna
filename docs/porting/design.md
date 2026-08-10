# 移植设计（design.md）

> superpowers Brainstorming/Design 交付物。来源：私有仓库 `FlanChanXwO/DNAUID`（GsCore 插件）→ 目标 `astrbot_plugin_dnaby`（AstrBot 4.27.1）。

## 1. 目标与决策

把 DNAUID 全面移植为原生 AstrBot 插件。已确认决策：

1. **原生重写集成层**：不引入 gsuid_core 兼容包；命令/发送/配置/DB/订阅/推送/Web/定时任务用 AstrBot 原生写法，仅复用纯逻辑（请求签名、伤害计算、PIL 渲染、攻略/wiki 素材、姓名别名、字体图片工具）。
2. **完整移植登录**：内嵌 Web/App 短信登录页、local 模式、QR、token、短信命令登录、外置传输（http_poll/sse/ws）全保留。
3. **命令改正则触发**：命令清单仿照原 `help.json` 生成 `commands.json`。
4. 使用 `/skill-astrbot-dev` 规范（metadata/requirements/main 聚焦/README/LICENSE）与 `/superpowers-skill` 方法论执行。

## 2. 现状（源）

- 445 文件、21 个 `dna_*` 模块 + `utils/`、92 个 py 文件、58 个文件 import gsuid_core。
- 约 60 条命令；82 处 `bot.send`；30+ gsucore API 符号；4 个定时任务；6 个登录 Web 路由；5 张 SQLModel 表；4 类订阅。
- 运行时 `.venv` 已具备全部重依赖（aiohttp/httpx/Pillow/pydantic/sqlmodel/sqlalchemy/aiosqlite/starlette/uvicorn/qrcode/jinja2/APScheduler/pycryptodome/websocket-client）。

## 3. 目标架构

```
astrbot_plugin_dnaby/
├── main.py                # Star 子类：@filter.regex 主门 + 分发；initialize/terminate；Web API 注册
├── metadata.yaml / _conf_schema.json / commands.json / requirements.txt
├── AGENTS.md / CLAUDE.md / docs/ / tests/ / ICON.png / LICENSE
├── dnaby/                 # 内部业务包（保留 dna_* 布局，rename 自 DNAUID）
│   ├── dna_*/             # 命令处理器 + 纯逻辑（draw_*/service/api）
│   └── utils/             # resource/config/database/image/fonts/notify/subscriptions/dna_api/constants
└── templates/             # 登录页（dnaby/templates）
```

## 4. 命令层设计

- `commands.json` 为唯一事实源：`key/group/name/desc/eg/regex/permission/handler`。
- `main.py` 用一个 `@filter.regex(MASTER)` 门（`MASTER = "|".join(regex)`），handler 内按序 `re.match` 取 named groups 再分发（仿 setu）。`@filter.regex` 只做 `re.search` 门、不传 Match，必须重跑 `re.match`。
- 权限：`permission=owner|admin` 用 `event.is_admin()` 或 sender role ∈ {admin, owner}；`user` 放行。

## 5. 发送层设计（关键）

- `dnaby/session.py` 定义 `EventContext`（只读字段：user_id/bot_id/group_id/at/text/command/raw_text/regex_dict/image_list/reply/user_pm）与 `Sender`（`send(text|bytes|Image|list)` 累积）。
- 业务函数签名 `(bot, ev)` → `(sender, ctx)`；handler 把 `Sender` 结果转 `yield event.plain_result/chain_result([Comp.Image.fromBytes(...)])`。
- 转发节点用 `Comp.Nodes`；`@` 用 `Comp.At`。

## 6. 各子系统映射

| 子系统 | gsucore | AstrBot 原生 |
|---|---|---|
| 触发 | `SV`+`on_*` | `commands.json` + `@filter.regex` |
| 发送 | `bot.send` | `Sender` → `yield event.*_result` |
| 配置 | `StringConfig`/`Gs*Config` | `AstrBotConfig` + `_conf_schema.json`；保留 `.get_config("Key").data` 读法 |
| 数据目录 | `get_res_path()` | `StarTools.get_data_dir(name)` |
| DB | gsucore base_models/exec_list | 本地 `utils/database/base.py`（sqlmodel+aiosqlite 私有 engine） |
| 订阅/推送 | `gs_subscribe`/`gss.target_send` | `utils/subscriptions.py` + `context.send_message(umo, chain)` |
| 定时任务 | `scheduler.scheduled_job` | `initialize()` 内 `asyncio` 循环，`terminate()` 取消 |
| 登录 Web | `web_app`(FastAPI) | `context.register_web_api` + 进程内 TTL 会话表 |
| 图片工具 | gsucore image_tools | 本地 `utils/image_utils.py`（PIL+qrcode+httpx） |
| 帮助/状态 | `register_help`/`register_status` | 帮助卡片（commands.json）+ 可选状态命令 |

## 7. 开放项 / 假设

- 内部包名沿用 `dnaby`（原 `DNAUID`），`dna_*` 布局保留以最小化路径改动。
- 旧 GsCore 部署（`atri`）的数据不迁移，全新开始。
- wiki/guide 素材（~33MB）随包带上；后续可选惰性下载/CDN。
- 数据目录：`data/plugin_data/astrbot_plugin_dnaby/`。
