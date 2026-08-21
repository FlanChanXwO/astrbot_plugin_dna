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
├── main.py                # Star 子类、命令方法安装和 bootstrap
├── src/
│   ├── bootstrap.py
│   ├── entry/
│   │   ├── commands/      # CommandSpec、registry、handler 生成器
│   │   ├── event.py       # 非命令事件边界
│   │   ├── response.py    # DTO → AstrBot 原生结果
│   │   ├── web.py
│   │   └── lifecycle.py
│   ├── modules/           # 显式索引的已实现 use case
│   └── infrastructure/    # 配置、持久化、HTTP、资源、渲染
├── metadata.yaml / _conf_schema.json / commands.json / requirements.txt
├── AGENTS.md / CLAUDE.md / docs/ / tests/ / ICON.png / logo.png / CHANGELOG.md / LICENSE
├── dnaby/                 # 内部业务包（保留 dna_* 布局，rename 自 DNAUID）
│   ├── dna_*/             # 命令处理器 + 纯逻辑（draw_*/service/api）
│   └── utils/             # legacy resource/config/database/image/fonts/notify/subscriptions/dna_api/constants
└── templates/             # 登录页（dnaby/templates）
```

## 4. 命令层设计

- `CommandSpec` 是代码事实源，字段为 `id/pattern/group/name/description/examples/permission/use_case`。
- `src/modules/index.py` 显式列出模块；`main.py` 为每个 spec 生成一个独立的真正
  async-generator class method，并应用 AstrBot 4.27.x 公共 `filter.regex` 与权限 decorator。
- handler 只重跑自己的正则并把 named groups 封装为 typed `CommandRequest`；不存在
  `MASTER_PATTERN` 或全局循环 dispatch。use case 返回框架无关 DTO，响应边界负责构造
  AstrBot 原生结果。
- `commands.json` 由 registry 生成，帮助 use case 读取同一 registry；未实现命令不注册、不展示。
- 权限：`user` 映射 `PermissionType.MEMBER`，`admin` 映射 `ADMIN`；AstrBot 没有独立 owner
  类型，当前 owner 由自定义过滤器精确匹配全局 `admins_id`，不等同于群管理员。

## 5. 发送层设计（关键）

- 新入口的 handler 将消息文本和自己的 named groups 封装为 typed `CommandRequest`；
  use case 不接收 `AstrMessageEvent`，也不依赖旧 `EventContext`、`Sender` 或 `MessageSegment`。
- use case 返回 `PlainTextResponse`、`ChainResponse`、`ImageResponse` 等框架无关 DTO；
  `src/entry/response.py` 统一调用 `event.plain_result`、`chain_result` 和 `image_result`。
- 业务消息段和图片组件只在后续 response/infrastructure 适配层出现；legacy `dnaby/`
  中的 `Sender` 仅作为迁移参考，不被新入口导入。

## 6. 各子系统映射

| 子系统 | gsucore | AstrBot 原生 |
|---|---|---|
| 触发 | `SV`+`on_*` | 代码 `CommandSpec` + 独立 `@filter.regex` handler |
| 发送 | `bot.send` | response DTO → `yield event.*_result` |
| 配置 | `StringConfig`/`Gs*Config` | `Pydantic DnabySettings` + `_conf_schema.json` 生成；legacy `.get_config("Key").data` 仅作参考 |
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
- fonts/wiki/guide/panel/image 素材放入插件外的私有 `FlanChanXwO/dnaby_resources`；插件只通过
  manifest + Git fast-forward-only 同步接口读取，建立/推送资源仓库需独立授权。
- 数据目录：`data/plugin_data/astrbot_plugin_dnaby/`。
