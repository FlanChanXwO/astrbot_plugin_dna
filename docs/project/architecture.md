# 架构

## `rewrite/v0.1` 当前入口

- 入口：`main.py` 仅实现 AstrBot `Star` 适配、从显式模块索引加载命令，以及
  `initialize()/terminate()` 对 `src.bootstrap` runtime 的转发。
- 组装：`src/bootstrap.py` 创建一个插件实例的 `PluginRuntime`，不在入口文件编排数据库、网络或业务。
- 命令：`src/entry/commands/` 定义 `CommandSpec`、只读 `CommandRegistry` 和 handler
  生成器；`src/modules/index.py` 是唯一显式模块索引。每个 spec 都成为一个独立的
  async-generator class method，并应用 AstrBot 公开的 `filter.regex` 与权限 decorator。
- 输入/输出：handler 将自己的正则 named groups、`EventActor` 和 runtime service
  视图封装成 `CommandRequest`；use case 返回框架无关 DTO；
  `src/entry/response.py` 再转换为 AstrBot 原生 text/chain/image result。
- 清单/帮助：`commands.json` 由 `scripts/generate_commands_manifest.py` 从代码 registry
  生成，帮助 use case 读取同一 registry。未迁移命令不会注册，也不会出现在帮助中。
- 生命周期：`src/entry/lifecycle.py` 按声明顺序启动、逆序停止扩展点；异常向上暴露，不伪造成功。
- Web 边界：`src/entry/web.py` 将 `WebRoute` 转换为 `Context.register_web_api`；当前 v0.1 没有业务路由，因此不会注册 Web API。
- 事件边界：`src/entry/event.py` 只通过 AstrBot 公开的 sender/self/group 方法提取
  `EventActor`，从公开消息链的 `At` 和 `Reply` 组件分别提取可选目标用户与引用消息
  ID；消息命令由每个动态 handler 的 AstrBot 正则过滤器接管，业务 use case 不持有原始
  event。
- 配置：`src/infrastructure/config/settings.py` 定义按领域分组的 Pydantic settings；
  `schema.py` 从同一份字段定义生成 `_conf_schema.json`，bootstrap 将 AstrBot 配置转换为
  `DnabySettings`。
- 持久化：`src/infrastructure/persistence/` 使用 SQLAlchemy 2 async 和
  `sqlite+aiosqlite`；`AsyncDatabase.transaction()` 是唯一的提交/回滚边界，repository
  显式接收 `AsyncSession`。Alembic 初始 revision 只创建新五表 schema，运行期文件为
  `dnaby.sqlite3`，不触碰 legacy `dnaby.db`；凭据模型提供脱敏 repr/快照。
- 账号：`src/modules/account/` 提供 token/短信 typed 登录、登录页 transport 边界、
  退出、UID 绑定/切换/删除/列表和凭据状态摘要；`AccountService` 在显式事务内协调
  normalized repository，`DnaApiAccountTransport` 只复用 legacy 纯 API，不复用旧事件、
  数据库或消息段类型。
- 隐私：`src/modules/privacy/` 提供个人偷窥/UID 开关、群强制设置、指定目标设置和
  查询解析；个人设置按 user+Bot 全局记录保存，群强制设置按 group+Bot 独立保存，群强制
  值按字段优先。指定命令要求 AstrBot admin 权限、群聊、有效 `At` 和目标绑定。
- 玩家查询：`src/modules/player/` 通过 typed transport 读取角色/武器展柜、角色详情
  和伤害结果；`src/infrastructure/rendering/` 生成运行期 PNG，详情响应携带
  per-response 的 `original_image_path` 原面板引用。AstrBot 4.27.x 公开结果边界没有
  已发送消息 ID 交付点，`原图` 命令显式报告未支持（Task 16.2）；默认 API 适配器只在
  transport 边界复用 legacy 纯请求、model 和伤害计算逻辑。
- 资料读取：`src/modules/encyclopedia/` 协调便签、周报、日历、图鉴、攻略、兑换码和只读
  别名；需要账号的便签/周报先经过隐私解析并使用目标用户凭据，日历和兑换码不读取账号。
  `EncyclopediaResourceStore` 只索引运行期资源，`EncyclopediaRenderer` 以完整 typed
  snapshot 生成可审查的 PNG，不按资料条目截断。
- 签到：`src/modules/checkin/` 通过 `CheckinTransport` 协调游戏/社区签到、签到日历和
  owner 批量签到；当天计数落到 `sign_records` 表（Task 9 的 `SignRecordRepository`）。
  真实写操作只走注入 transport（默认 `DnaApiCheckinTransport` 复用 legacy 纯 API），
  服务层不接触旧事件/数据库/消息段；`CheckinRenderer` 生成 1300 宽日历 PNG。
- 订阅与计划任务：`src/infrastructure/subscriptions/` 提供框架无关的 JSON 订阅存储
  （按 type+会话去重）；`src/infrastructure/scheduler.py` 的 `SignScheduler` 在
  `initialize()` 创建每日自动签到与记录清理任务、`terminate()` 取消，重复初始化幂等。
  自动签到摘要经注入的推送闭包（绑定 `Context.send_message`）发给订阅者；`sleep/now`
  可注入，离线测试不依赖真实时钟。
- 资源：`src/infrastructure/resources/` 只通过参数列表调用 Git，首次浅克隆、后续
  `pull --ff-only`，同步前后检查 origin、干净 worktree 和完整 `resource_manifest.json`；不
  强制覆盖本地修改。bootstrap 从同一运行期 `resources/` 根注入玩家的 `ResourceMap` 与
  `EncyclopediaResourceStore`，字体不再从源码读取。生成 PNG 仅在受控 `rendered/` 根登记给
  AstrBot 事件期清理，资源资产不会被登记为临时文件。
- 当前阶段：`rewrite/v0.1` 已注册 `帮助`、Task 10 账号、Task 11 隐私、Task 13 玩家
  查询和 Task 14 资料读取 use case，共 35 条命令；其余旧功能不会在新入口中隐式注册。

## `legacy-reference` 迁移参考

- 旧命令入口：`dnaby/dispatch.py` 的 `MASTER_PATTERN` 与全局分发，后续迁移到显式 `CommandSpec` registry。
- 旧业务包：`dnaby/dna_*/` 与 `dnaby/utils/` 保留在重构区作为分阶段迁移参考；不应由新的 `main.py` 直接编排。
- 旧配置、数据库、订阅和登录模块的迁移边界见 [design.md](../porting/design.md) 与 `goal-1/tasks.md`。
