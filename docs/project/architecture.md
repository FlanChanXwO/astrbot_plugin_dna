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
- 生命周期：`src/entry/lifecycle.py` 按声明顺序启动、逆序停止扩展点；登录页 listener 在
  scheduler 之前启动，终止时先取消登录等待并释放 listener，再释放数据库；异常向上暴露，不伪造成功。
- Web 边界：`src/entry/web.py` 将 `WebRoute` 转换为 `Context.register_web_api`；`src/entry/admin_web.py` 提供统一认证、请求解析、错误/HTTP 状态映射和 no-store JSON，管理路由仅通过 Dashboard extension dispatcher 注册在 `/astrbot_plugin_dnaby/admin/*`，不建立独立未认证入口。
- 管理页：`pages/dashboard/` 是由 AstrBot Dashboard 承载的 PetiteVue 静态页，只通过上述已认证
  dispatcher 访问任务/探测、账号/预览和角色别名三个功能区；写操作在服务端确认并
  成功后重新读取状态，不提供账号/任务创建或帮助命令管理。
- 事件边界：`src/entry/event.py` 只通过 AstrBot 公开的 sender/self/group 方法提取
  `EventActor`，从公开消息链的 `At` 和 `Reply` 组件分别提取可选目标用户与引用消息
  ID；消息命令由每个动态 handler 的 AstrBot 正则过滤器接管，业务 use case 不持有原始
  event。
- Agent Tools：`src/entry/agent_tools/` 通过 AstrBot 官方 `FunctionTool`、
  `Context.add_llm_tools` 和 `unregister_llm_tool` 提供 16 个只读查询与唯一的 `dnaby_sign`
  写入口；`AgentToolsLifecycle` 在 runtime 的 initialize/terminate 中按总开关注册和解除，
  `AgentQueryCatalog` 复用领域查询适配器。查询身份只来自 `AstrAgentContext.event`，签到还要求
  原始消息的明确肯定意图，并以事件消息 ID 幂等；具体工具 schema、返回和安全边界见
  [Agent Tools 使用说明](../usage/agent-tools.md)。
- 配置：`src/infrastructure/config/settings.py` 定义按领域分组的 Pydantic settings；
  `schema.py` 从同一份字段定义生成 `_conf_schema.json`，bootstrap 将 AstrBot 配置转换为
  `DnabySettings`。
- 持久化：`src/infrastructure/persistence/` 使用 SQLAlchemy 2 async 和
  `sqlite+aiosqlite`；`AsyncDatabase.transaction()` 是唯一的提交/回滚边界，repository
  显式接收 `AsyncSession`。Alembic 初始 revision 只创建新五表 schema，运行期文件为
  `dnaby.sqlite3`，不触碰 legacy `dnaby.db`；凭据模型仅保留 App 字段并提供脱敏
  repr/快照，`0004_app_credentials_only` 物理删除五个 Web 列。
- 账号：`src/modules/account/` 提供 token/短信 typed 登录、`LoginFlowCoordinator` 登录页
  与外置 transport 边界、退出、登录后自动绑定、UID 切换/删除/列表和 App 凭据状态摘要；`AccountService` 在显式事务内协调
  normalized repository，`DnaApiAccountTransport` 只复用 legacy 纯 API，不复用旧事件、
  数据库或消息段类型。Web 凭据、Web fallback 和 Web 登录路由不属于当前契约。
- 隐私：`src/modules/privacy/` 提供个人偷窥/UID 开关、群强制设置、指定目标设置和
  查询解析；个人设置按裸 `user_id` 全局记录保存，群强制设置按裸 `group_id` 独立保存，
  群强制值按字段优先。相同 `user_id` 在不同平台或 Bot 上视为同一身份，跨平台字符串碰撞
  是已接受的部署风险；指定命令要求 AstrBot admin 权限、群聊、有效 `At` 和目标绑定。
  `EventActor.bot_id` 只保留为运行期投递/legacy transport 上下文，不参与账号或隐私查询。
- 玩家查询：`src/modules/player/` 通过 App-only typed transport 读取角色/武器展柜和角色详情；
  正常详情路径不调用伤害计算 API，也不渲染伤害区块；`src/infrastructure/rendering/` 通过 T2I
  生成运行期 JPEG artifact。详情响应携带 per-response 的 `original_image_path` 原面板引用，
  `原图` 命令在当前平台显式报告未支持。`PlayerCache` 将 typed 玩家数据和完整卡片接入统一
  `CacheManager`；卡片按 generation 版本、数据摘要、身份和显示参数隔离，placeholder 渲染只允许
  本次发送，不覆盖完整缓存。玩家模块提供普通用户单角色/全部角色刷新、单角色/全部角色清理和
  管理员 UID+角色刷新；刷新按 identity/role tags 精准失效。单角色刷新固定返回新的完整卡片，
  批量刷新只返回汇总。
- 资料读取：`src/modules/encyclopedia/` 协调便签、周报、日历、图鉴、攻略、兑换码和只读
  别名；需要账号的便签/周报先经过隐私解析并使用目标用户凭据，日历和兑换码不读取账号。
  `EncyclopediaResourceStore` 只索引运行期资源，`EncyclopediaRenderer` 以完整 typed
  snapshot 生成可审查的 PNG，不按资料条目截断。
- 签到：`src/modules/checkin/` 通过 `CheckinTransport` 协调游戏/社区签到、签到日历和
  admin 批量签到；当天计数落到 `sign_records` 表（Task 9 的 `SignRecordRepository`）。admin 身份由 AstrBot 权限过滤器授权。
  真实写操作只走注入 transport（默认 `DnaApiCheckinTransport` 复用 legacy 纯 API），
  服务层不接触旧事件/数据库/消息段；`CheckinRenderer` 生成 1300 宽日历 PNG。
- 订阅与计划任务：`src/infrastructure/subscriptions/` 提供框架无关的 JSON 订阅存储
  （按 type+会话去重）；`src/infrastructure/scheduler.py` 的 `SignScheduler` 在
  `initialize()` 创建每日自动签到与记录清理任务、`terminate()` 取消，重复初始化幂等。
  `CacheMaintenance` 同样在 `initialize()` 启动、`terminate()` 取消，统一清理持久缓存和受控
  `rendered/` 孤儿文件；ResponseFactory 登记发送文件的租约，清理时跳过活动租约。
  自动签到摘要经注入的推送闭包（绑定 `Context.send_message`）发给订阅者；`sleep/now`
  可注入，离线测试不依赖真实时钟。
- 客户端更新：`src/modules/client_updates/` 提供国服 PC/安卓查询、群聊管理员订阅、平台筛选、
  成功观察基线和框架无关的推送 DTO；手动查询不写基线，首次订阅/首次成功检查只建立缺失基线。
  `ClientUpdatesScheduler` 独立注册 `dnaby_client_update_poll`，周期为
  `interval@{notifications.client_update_check_minutes}m`，不与公告任务共用周期。`ClientUpdateDeliveryService`
  按 `Subscription.extra_data.platforms` 筛选目标，`ClientUpdatePushAdapter` 仅在 OneBot 且开关开启时
  尝试合并同轮平台消息，能力不可用或失败则降级为逐平台普通消息并记录安全原因；bootstrap 已绑定
  `Context.send_message`，普通消息使用 `MessageChain`，OneBot 合并转发使用原生 `Nodes`。状态 store 持久化
  `event_key`、首次固定目标及每个目标的 pending/delivered；每轮先重试历史 pending，再生成当前事件，
  取消/停用会清理目标，事件全部完成后清理。
- 通知读取：`src/modules/notices/` 通过 `NoticesTransport` 读取密函（角色/武器/魔之楔分节，
  复用 legacy `get_default_role_for_tool` 的 `instanceInfo`）、公告列表与详情（公共 BBS，
  HTML 清洗复用 `dnaby/dna_ann/utils` 纯逻辑）。公告 transport 解包 `postDetail`、完整翻页
  并保留带 query/hash 或无扩展名的图片 URL；`NoticesRenderer` 为公告列表和详情生成 T2I 图片，
  密函按模式生成默认 1700×900 或简洁分栏图；公告均按 typed snapshot 保留完整内容，详情多页
  通过 `MultiImageResponse` 在同一回复发送。
  手动详情图片失败返回固定失败文案，不合成透明/深色占位图；运行期的公告源图、列表卡和详情
  页面使用 `CacheManager` 的 `announcement` 类型，以内容 fingerprint 隔离，并与玩家、密函共用
  `cache.ttl_hours`；`0` 禁用持久缓存，`-1` 永久有效。
  订阅复用 `SubscriptionStore`（密函按 user+会话、公告按群聊作用域，`extra_message`/`extra_data`
  存密函名称与订阅级时间窗口）；`NoticesScheduler` 按配置的每小时 `HH:<minute>` 推送密函、按分钟轮询公告
  （`AnnStateStore` 保留旧 ID 列表，`AnnDeliveryStateStore` 记录首次观察目标与成功目标），密函按
  配置的每小时分钟触发并在当前小时快照有效时只推送一次；详情、
  渲染或目标发送失败时保留待重试目标，不发送标题 fallback。推送经注入闭包绑定
  `Context.send_message`，只有发送成功才落成功状态；文本/图片载荷分别映射为 Plain/Image 组件。
- 资源状态：`src/modules/operations/` 只提供公共资源状态/下载；`panel_custom/` 是已移除
  面板管理能力后的遗留目录，插件不读取、统计或删除其中内容。别名维护由
  `src/modules/admin/aliases.py` 提供角色和武器两类独立 custom 文件。
  资源更新经 `ResourceUpdateService` 调用 `ResourceSnapshotCoordinator`：Git cache 只执行
  `main` 的浅克隆/fetch，候选先由 `git archive FETCH_HEAD` 物化并完整校验，再
  `merge --ff-only FETCH_HEAD`，计算完整文件树 SHA-256，最后原子发布 `resource_generations/<sha>/`
  和带摘要的当前指针。候选校验包含 manifest 声明的文件哈希、路径安全和 PIL 图片解码。
  `下载全部资源` 把 Git/候选错误映射为可见错误，不自动覆盖本地修改；旧快照在失败时继续服务。
  启动预热与该命令共享 single-flight，同步终止前会排空后台任务。
- 更新历史不注册聊天命令，长期记录统一放在仓库根目录 `CHANGELOG.md`。
- 资源：`src/infrastructure/resources/` 只通过参数列表调用 Git，规范 origin 固定为公共
  GitHub 资源仓库；首次 `main` 浅克隆，后续只执行 `fetch --no-tags origin main`，可用临时
  `url.*.insteadOf` 注入 GitHub 加速前缀。同步前后检查 origin、main checkout、干净 worktree
  和完整 `resource_manifest.json`；不强制覆盖本地修改。bootstrap 从当前已验证 generation
  注入玩家的 `ResourceMap` 与 `EncyclopediaResourceStore`，并订阅发布事件刷新 renderer、
  别名和资源状态视图。每次读取持有 generation lease；旧 generation 在最后一个 lease 释放后
  回收，重启只清理孤立 generation，不触碰 `panel_custom/`。生成 PNG 及 generation 内直出素材
  的安全副本仅在受控 `rendered/` 根登记给 AstrBot 事件期清理，并由 `RenderedFileStore` 保护
  活动发送文件、清理过期孤儿。
- 图片下载：`src/utils/image_utils.py` 的 `ImageFetcher` 是 legacy 图片调用方共用的 HTTP/缓存
  边界；连接/超时、429、5xx 的重试、`Retry-After`、PIL 校验、同目录临时文件和原子替换均在
  此处完成。`download()` 只保留参数兼容入口；失败不写透明假图，已有文件复用前必须解码校验。
- 资源分层：公共基础资源只来自 `resources/` 与已验证的 `resource_generations/`；legacy
  `resource/`、`other/ann_card/` 等是插件数据目录内的运行期图片缓存/补充资源，
  `panel_custom/` 单独保存用户上传内容。账号私有资源不得进入公共资源仓库或 manifest。
- 三仓边界：公共资源仓库只承载 manifest、素材、兑换码和 schema；GPL-3.0 编辑器仓库独立
  提供类型化表单、GitHub App OAuth/投稿/Webhook Check。编辑器生成的 PR 必须落到资源仓库
  `main` 后，插件才会从 canonical GitHub origin 的 `main` fetch、校验并发布 generation；
  插件不拉取编辑器源码，也不把镜像或投稿分支当作发布源。资源仓库的第三方素材不因仓库
  公开或插件 GPL-3.0 而获得统一许可。
- 当前阶段：当前 main 已注册 `commands.json` 中的 63 条命令；公共帮助和角色/武器列表属于
  普通用户，管理员功能统一映射 AstrBot `ADMIN`，未迁移及已删除命令不会在新入口中隐式注册。

## HTML/T2I 图片渲染

生成型用户可见图片由 `src/infrastructure/rendering/` 的 Jinja2 模板和 AstrBot 全局 T2I 适配器生成。
资源先编码为 `data:` URI，`HtmlRenderer` 负责统一截图规格和返回图片格式校验；渲染异常在命令 handler
边界记录分类与内部原因，并返回 `notify.py` 定义的通用失败文案。插件不修改全局 T2I 网络策略。

## `legacy-reference` 迁移参考

- 旧命令入口：`dnaby/dispatch.py` 的 `MASTER_PATTERN` 与全局分发，后续迁移到显式 `CommandSpec` registry。
- 旧业务包：`dnaby/dna_*/` 与 `dnaby/utils/` 保留在重构区作为分阶段迁移参考；不应由新的 `main.py` 直接编排。
- 旧配置、数据库、订阅和登录模块的迁移边界见 [design.md](../porting/design.md) 与 `goal-1/tasks.md`。
