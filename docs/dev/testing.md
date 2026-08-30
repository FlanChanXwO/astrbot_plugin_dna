# 测试

## 命令
```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

## 测试范围（tests/）
- `test_command_registry.py` — `CommandSpec` 校验、显式模块索引、重复加载、named
  parameters、动态 async-generator handler、AstrBot 公开正则/权限过滤器和帮助输出。
- `test_commands.py` — `commands.json` 与代码 registry 生成投影一致；legacy 分发器回归单独保留在
  `test_dispatch.py`，不属于 rewrite 入口。
- `test_config.py` — legacy 配置 wrapper 的兼容回归。
- `test_config_resources.py` — Pydantic 分组配置、生成 schema 的 AstrBotConfig 递归解析、
  resource manifest 路径校验、私有 Git clone/fetch/fast-forward 失败可见性和本地修改保护。
- `test_goal3_resource_acceleration.py` — Task 16 的资源加速、canonical origin、单分支 Git
  参数与 bootstrap 注入。
- `test_goal3_resource_generations.py` — Task 17/O08 的 `FETCH_HEAD` archive 候选、manifest 文件
  哈希、PIL 图片解码、完整内容摘要、原子 generation 发布、失败保留旧快照、并发 lease、renderer
  绑定与重启孤立物清理。
- `test_resource_service.py`、`test_goal1_o08_resources.py` — 资源预热与管理员下载 single-flight、
  终止排空和 bootstrap 生命周期注入。
- `test_goal1_o09_image_fetcher.py` — 图片下载的瞬态重试、`Retry-After`、非重试状态、PIL 完整
  校验、原子缓存、损坏缓存修复、single-flight、legacy 调用方复用和失败日志脱敏。
- `test_goal1_d03_review.py` — O07–O09 的符号链接路径边界、取消后后台同步失败可观测性，以及
  资源/图片缓存的故障注入审查。
- `test_goal1_o16_agent_tools.py` — Agent 查询 request/result、当前事件身份提取、共享领域查询
  适配和身份参数拒绝。
- `test_goal1_o17_agent_tools.py` — 16 个只读工具的官方注册、JSON envelope、图片发送、路径/二进制
  脱敏、身份覆盖拒绝和图片失败语义。
- `test_goal1_o18_agent_tools.py` — 签到原始消息确认、模型参数拒绝、当前 UID、消息 ID 幂等、总开关
  和 runtime 生命周期。
- `test_goal1_d06_agent_tools.py` — 信息/示例 prompt 负向确认、工具范围、并发注册、注销残留重试和
  热重载清理。
- `test_goal3_task19.py` — 使用临时 bare Git 和编辑器 `test:task19` 联合验证公共资源
  manifest/schema、Worker PR Check、插件 `main` 下载/generation/兑换码消费，以及旧数据目录
  与 `panel_custom`/数据库/订阅文件的无损升级。
- `test_persistence.py` — SQLAlchemy async SQLite 路径、repository 显式事务提交/回滚、五表
  metadata、凭据脱敏和 Alembic 初始 revision；Alembic 未安装时真实 upgrade/downgrade 测试会
  显式 skip，静态 revision 契约仍执行。
- `test_account.py` — typed 登录输入、fake transport、账号事务、绑定生命周期、凭据状态
  摘要和网络/状态码/服务端错误脱敏。
- `test_account_commands.py` — AstrBot 事件 fixture 到 typed actor、named/空 UID 参数和
  runtime service 注入边界。
- `test_privacy.py` — 个人/群组隐私默认值、字段优先级、取消恢复、目标绑定、AT 查询解析、
  并发 upsert 和 SQLite 全局作用域唯一性；所有隐私写入均使用隔离 SQLite。
- `test_privacy_commands.py` — 14 条隐私命令的 registry 权限、公开 `At` 目标提取和缺失目标边界。
- `test_player.py` — 角色概览/详情 fixture、动态图片尺寸、完整文本/布局/资源元数据、伤害
  结果、并发详情各自的原面板引用和伤害失败内容脱敏。
- `test_goal1_o10_player_cache.py` — 玩家 JSON/PNG 缓存的 fresh/stale/24 小时保留语义、旧卡
  回退、不完整占位隔离、资源版本换代和多条件精准失效。
- `test_goal1_o11_refresh_and_cleanup.py` — 普通/管理员角色刷新、全量玩家缓存清理、
  `refresh_send_card`、rendered 孤儿清理、活动发送文件租约和维护任务生命周期。
- `test_player_commands.py` — 玩家命令正则、显式 registry、AstrBot `Reply` 消息 ID提取和
  service 缺失边界。
- `test_checkin.py` — 签到成功/已签到/transport 失败/日历精简/帖子遍历/批量聚合，
  隔离 SQLite 记录落盘与 1300 宽日历 PNG。
- `test_checkin_commands.py` — 签到命令归属、正则、权限和生成 handler 的纯文本结果。
- `test_checkin_transport.py` — legacy 签到 payload 映射、code 711/10000 语义和错误脱敏。
- `test_subscription_store.py` — 订阅 JSON 持久化、type+会话去重、显式删除和损坏文件可见失败。
- `test_scheduler.py` — 计划任务幂等 start/stop、定时任务门控只保留清理任务、自动签到推送订阅者和
  2 天前记录清理。
- `test_write_contracts.py` — 写入型命令权限审计、每条写入命令离线分发契约和
  “只调用注入 transport”边界（离线验证 ≠ 真实行为已验证，见
  [offline-write-contracts](../porting/offline-write-contracts.md)）。
- `test_notices.py` — 密函/公告读取 fixture、密函 1700×900/简洁分栏 PNG、公告 1080 宽 PNG、公告序号详情、空数据与
  transport 失败脱敏。
- `test_goal1_o12_announcements.py` — 公告 `postDetail` 解包、空正文拒绝、完整分页、序号索引、
  query/hash/无扩展名图片 URL、多页 `MultiImageResponse`、列表/详情失败文案、完整缓存与
  fingerprint 失效、源图校验缓存和列表模板无无依据截断。
- `test_goal1_o12a_delivery.py` — 公告旧状态迁移、首次目标集合、部分目标失败重试、详情失败跳过、
  参数化缓存键、IP/RSA fallback、账号/帖子缓存隔离和登录日志脱敏。
- `test_notices_commands.py` — 密函/公告命令归属、正则命名参数与生成 handler 边界。
- `test_notices_transport.py` — legacy 密函 `instanceInfo`、公告列表/详情映射与错误脱敏；
  覆盖网络失败/状态码错误/页面结构变化/空正文四类可观测错误，并断言 Cookie/token 原文不进异常。
- `test_notices_subscriptions.py` — 密函订阅增删/去重/推送时间、图片/文本会话开关、公告
  群订阅、计划任务文本/图片推送与公告轮询去重。
- `test_notices_scheduler.py` — 通知计划任务幂等 start/stop 与配置解析。
- `test_operations.py` — 面板图上传（WebP/sha1 去重/失败计数）、列表、删除、压缩和资源
  状态（隔离目录 fixture）。
- `test_operations_commands.py` — 面板/资源命令归属、正则、`images_from_event` 提取与生成
  handler。
- `test_resource_service.py` — 资源下载成功（克隆/更新）、Git 缺失/远端不匹配/本地修改/
  同步失败可见错误。
- `test_player_transport.py` — legacy role API payload 到 typed overview 的映射和 transport
  错误脱敏。
- `test_session.py` — `EventContext` 映射（mock `AstrMessageEvent`）、`Sender` 累积与结果转换。
- `test_database.py` — 5 表 CRUD + 迁移（临时 sqlite 文件）。
- `test_subscriptions.py` — 订阅增删改查 + 目标解析。
- 各功能域纯逻辑（name_convert、damage、sign 解析等）。
- `test_html_renderer.py`、`test_rendering_assets.py` — Jinja autoescape、截图参数、结果类型、资源
  data URI 和全局 T2I 配置不被插件改写。
- `test_command_registry.py` — HTML/T2I 渲染异常只向用户暴露统一文案，内部原因留在日志。

## 原则
- 先写失败测试（Red）→ 最小实现（Green）→ Refactor。
- 用 mock 构造 `AstrMessageEvent`，不依赖真机。
- 生产 schema 变更走 Alembic；`create_schema_for_tests()` 只用于隔离测试，不能替代部署迁移。
- `AsyncDatabase.transaction()` 的 runtime 内写锁只用于保护 SQLite 事务一致性，没有固定
  超时、重试或静默降级；首次部署仍须先执行 Alembic `upgrade head`。

## AstrBot 集成边界

当前阶段只用 AstrBot 本地 SDK、fake Context、事件 fixture 和原生响应构造方法验证
插件加载、handler 注册和响应结果。账号与隐私写入只在隔离 SQLite 中执行；不执行真实
NapCat、OneBot、手机号验证码、token 或外部登录服务。

## 三仓发布前门禁

编辑器仓库从其根目录执行：

```bash
npm ci
npm test
npm run typecheck
npm run build
npm run deploy:dry-run
```

`npm test` 不隐式运行跨仓 `test:task19`；插件测试会创建 fixture 并注入
`DNA_TASK19_FIXTURE` 后调用它。资源仓库不承载编辑器测试或依赖，发布前至少用 Python/JSON
工具检查 manifest、schema 和 data 语法，并通过编辑器 `resource-contract` Check。真实
Cloudflare/GitHub App/Turnstile/Webhook/ruleset 验收仍须按外部运维 runbook 单独记录，不能以
本地 fixture 或 `deploy:dry-run` 冒充。
