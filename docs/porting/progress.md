# 移植进度（progress.md）

> 更新于 2026-08-12。superpowers 迁移记录；当前 rewrite 阶段审查见
> [review-v0.2-debug.md](review-v0.2-debug.md)、[review-v0.3-player.md](review-v0.3-player.md) 和
> [review-v0.3-encyclopedia.md](review-v0.3-encyclopedia.md)、[review-v0.3-debug.md](review-v0.3-debug.md)，legacy 完整审查见 [review.md](review.md)，
> legacy 交付结论见 [final_report.md](final_report.md)。

> 重构区说明：本文主体记录的是 `legacy-reference` 的历史移植状态。当前 `rewrite/v0.1`
> 已切换为 `main.py` + `src/` 薄入口，代码 registry 已包含帮助、账号、隐私、玩家查询和资料读取共 35 条命令；
> 其余历史命令、Web 路由和业务生命周期仍按 `goal-1/tasks.md` 分阶段迁移。

### rewrite Task 13 — 玩家查询 ✅

- 已登记 `role_info_card`、`role_detail_card` 和 `role_original_image`；新增 typed
  `PlayerService`、可注入 player transport、legacy 纯 API/model/伤害适配和 Reply 消息 ID
  边界。
- 概览和详情渲染在运行期 plugin data 生成动态 PNG，完整保留合法角色、武器、技能、魔之楔、
  溯源和伤害字段；`OriginalImageCache` 只按显式消息 ID返回原面板图。
- 详细行为矩阵、已知差异和图像验证格式见 [review-v0.3-player.md](review-v0.3-player.md)。

### rewrite Task 14 — 资料读取 ✅

- 已登记日常便笺、周报、日历、图鉴、攻略、兑换码和只读别名共 9 条命令；新入口只读取
  新 SQLAlchemy schema 中的当前 UID/凭据，写入型别名能力仍未注册。
- 新旧 API 的 typed transport、运行期资源索引和动态 PNG 渲染均通过隔离 fixture 验证；有效兑换码
  保留各自截止时间，图片不截断合法资料项。
- 详细行为矩阵、可见差异和资源边界见 [review-v0.3-encyclopedia.md](review-v0.3-encyclopedia.md)。

### rewrite Task 16 — 查询/百科集中审查 ⚠️

- Task 15 的结构实测、动态字段 mask 和未接受视觉差异保持明确状态；图片/资源/时间敏感
  项没有因 fixture 或 placeholder 被标为通过。
- 审查发现原图没有生产消息 ID 登记路径、玩家/百科资源契约未接入、伤害失败可能回显上游
  内容，以及生成 PNG 没有事件期清理。后续先执行 Task 16.1 和 Task 16.2，再恢复对这些能力
  的功能性主张。
- 完整证据和修复边界见 [review-v0.3-debug.md](review-v0.3-debug.md)。

## 当前状态

`astrbot_plugin_dnaby` 已完成从 GsCore DNAUID 到原生 AstrBot 的代码层移植。当前入口可被 AstrBot 以 `data.plugins.astrbot_plugin_dnaby.main` 动态加载，56 条命令、18 个功能模块、5 张 SQLModel 表、登录 Web 路由和 4 个定时任务均已接入。

硬约束已核对：源码不 import `gsuid_core` / `gsucore`；运行期数据库、订阅和资源写入 AstrBot `plugin_data` 数据目录；`commands.json` 与分发表同步；入口不承载业务编排。

## 已完成

### Phase 0 — 脚手架 ✅

- 插件骨架、`metadata.yaml`、`requirements.txt`、`README.md`、`LICENSE`、`.gitignore`、`.pre-commit-config.yaml`。
- `AGENTS.md` 与 `CLAUDE.md` 镜像规则；`docs/` 索引、设计、计划、开发、使用、架构和 legacy 档案。
- `dnaby/` 业务包、登录模板、字体与图片素材；`commands.json` 和 `_conf_schema.json`。

### Phase 1 — 原生基建 ✅

- AstrBot 事件/发送适配：`EventContext`、`Sender`、消息段和图片转换。
- 配置管理与 schema 生成；对象型配置包含 AstrBot 所需的 `items`。
- 私有 aiosqlite 数据库、`with_session` / `with_lock`、五张业务表和 CRUD。
- `StarTools` 对应的数据目录适配、JSON 订阅持久化、原生推送、API 请求签名与统一响应模型。
- 正则主门、组内重匹配、权限检查和命令分发；动态加载与开发态顶层导入均可用。
- 纯文本通知统一经过 `send_dna_text()`，保留图片、混合消息链和转发节点的原生发送路径。
- 订阅增删改的完整读改写事务统一受实例锁保护，新增并发回归测试。

### Phase 2–6 — 功能域 ✅（代码层）

- 免登录查询：角色、伤害、日历、体力、周报、公告、攻略、图鉴、兑换码、更新记录。
- 账号与隐私：绑定/切换/删除 UID、App/Web/token/短信登录、退出、token 查看、隐私设置。
- 订阅与定时：签到、密函、公告推送、记录清理；`initialize()` 启动，`terminate()` 等待取消完成。
- 别名、资源下载、自定义面板图、原图和状态模块；`dna_status` 按设计作为可选能力保留统计函数，不注册 Dashboard 指标。

### 真实 E2E ✅（2026-08-09）

- 通过本机 AstrBot `6196`、OneBot HTTP `6199`、NapCat 出站链路覆盖 `commands.json` 的
  56 条命令；每条至少验证了正常路径或不会改动真实账号的错误/空数据路径。
- 已验证真实数据库中的登录数据仍可被查询，原绑定 UID 未变化；测试用户、订阅、别名和
  自定义面板图均在收尾检查后清理。
- `dna登录` 已验证消息命中、链接立即出站、登录页 `HTTP 200` 和表单 DOM；旧 auth 返回
  `HTTP 404` 无效会话页。无参数登录仍会在发送链接后等待网页提交，不再延迟发送链接。
- 真实 OneBot 图片段已验证上传、列表和按 ID 删除；图片转换器现使用 AstrBot 组件的
  `convert_to_file_path()`。

## 验证结果

从插件目录使用 runtime `.venv`（Python 3.12.13）：

| 检查 | 结果 |
|---|---|
| `python -m pytest -q` | `55 passed`，仅 AstrBot `audioop` 弃用警告 |
| `ruff check .` | 通过 |
| `uv run --offline ruff check data/plugins/astrbot_plugin_dnaby` | 通过 |
| `pyright` | 0 errors / 0 warnings（项目配置覆盖 `dnaby` 与 `tests`） |
| `python -m compileall -q .` | 通过 |
| `import main` | 通过 |
| `import data.plugins.astrbot_plugin_dnaby.main` | 通过 |
| 命令清单/分发 | 56 条、18 模块，pytest 一致性断言通过 |
| Dashboard 重载 | `ASTRBOT_SKIP_PLUGIN_REQUIREMENTS_SYNC=1 ... reload-plugins.sh 6196 astrbot_plugin_dnaby` 返回 `重载成功` |
| 本机真实 E2E | 56 条命令均有入站 `204`；NapCat 出站日志与预期输出一致，密函测试在无订阅时无直接回复 |

## 已修复的迁移边界

- 修正公告模块失效导入、示例命令与 regex 不一致、更新日志 import 时执行 git、登录路由注册契约和入口动态包路径。
- 用 `asyncio.timeout` 替换额外的 `async-timeout`；统一上海时区并兼容 aware/naive datetime。
- 别名文件读写移入 `asyncio.to_thread`；数据库装饰器使用 `ParamSpec` 隐藏内部 session 参数，Pyright 不再泄露错误签名。
- 登录会话标识改为进程内 HMAC；API 调试日志不再记录 token/cookie/完整请求响应；外置轮询网络失败显露 `TransportError`。
- schema 对象补齐 `items`，实际 AstrBot 4.27.1 重载验证通过。
- 公告缓存按 `ClassVar` 语义写回；Pillow 路径、SQLModel 元类参数和 SQL 表达式补齐源码级类型检查。

## 尚未覆盖 / 后续

- 未执行真实手机号/短信验证码提交、有效 token 登录和外置 `http_poll/sse/ws` 服务验收；本轮
  只验证了本地登录页、无效 token 分支和已落库账号的查询链路。
- 指定隐私命令的真实 `@` 目标路径受本机 OneBot 群成员信息查询响应缺失影响；无 `@` 错误路径、
  临时未绑定 `@` 路径和其余群隐私命令均已验证，未将该环境问题伪装成插件成功。
- 订阅锁是 `SubscriptionStore` 实例级锁；当前运行时使用全局 `gs_subscribe` 单例，未来若多进程或多实例共享同一 JSON 文件，仍需引入文件级锁或单写者方案。
- 插件目录及 runtime 根目录均未发现 Git 仓库，本次未初始化 Git，也未创建提交。
