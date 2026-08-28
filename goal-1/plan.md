# dnaby 稳定性、原版行为对齐与 Agent Tools 改进计划

> 状态：**执行中**。用户已明确要求启动本目标；后续按 `tasks.md` 顺序每轮只推进一个 task。生产部署与插件重载仍须满足本计划的显式前置条件，不在本轮默认执行。

## 1. 目标

分三个可独立交付、可独立回滚的阶段改进 `astrbot_plugin_dnaby`：

1. 修复公告、帮助菜单、动态前缀、版本号、更新记录以及卡片/周报/面板等命令与原版不一致的问题。
2. 建立统一的资源下载、完整性校验、资源快照、卡片缓存、公告缓存、自动过期与显式刷新机制。
3. 接入 AstrBot Agent Tools，让 AI 可以安全地查询游戏信息，并在严格确认和身份约束下为当前用户签到。

每阶段均使用 TDD，生成一个独立插件 commit SHA；生产环境部署固定 SHA，通过 AstrBot 自带的定向插件热重载完成，不默认重启容器。

## 2. 非目标与边界

- 不引入 `gsuid_core` / `gsucore`。
- 不把业务编排写入 `main.py`；入口只负责注册、生命周期与框架适配。
- 不在本轮初始化中修改业务代码、配置、文档投影、生产仓库或运行期数据。
- 不将生产 Cookie、token、Dashboard 密码、SQLite、日志或密钥提交到仓库或输出到终端。
- 不允许 Agent Tools 修改账号、凭据、隐私、订阅、资源或管理配置。
- 不允许模型提供 UID、用户 ID 或“已确认”标志来绕过当前消息的真实身份与确认判断。
- 不以重启 AstrBot 容器作为正常插件更新步骤；定向热重载失败时先停止并回滚，不扩大操作范围。
- 不做真实 QQ 端到端依赖；使用 AstrBot 适配器模拟，并由 Agent 实际检查生成图片。
- 不执行真实签到副作用测试；签到传输层必须使用 fake transport 验证。

## 3. 已确认的设计

### 3.1 第一阶段：命令与帮助行为对齐

#### 权限与请求上下文

- 权限模型收敛为 `user` 与 AstrBot `admin`，移除插件自定义 owner 分支。
- 在 `CommandRequest` 中建立一次性的权限快照，命令匹配、帮助过滤与工具调用共享同一判定。
- 帮助菜单根据当前用户权限展示：普通用户只看到用户命令，管理员看到用户命令和管理员命令。

#### 动态前缀与帮助清单

- 命令前缀只来自 AstrBot/插件配置，不隐式追加 `d`，修复帮助菜单动态前缀总含 `d` 的问题。
- 命令 registry 是唯一事实源；帮助菜单从 registry 生成，必须纳入角色列表等所有已注册且可见命令。
- 帮助中的版本号从插件 metadata/单一版本源读取，不允许模板或 handler 硬编码。
- `help.json` 不再承担命令事实源；若保留，只能存表现层数据。
- 帮助渲染采用进程内缓存，键至少包含前缀、权限与插件版本；插件重载/终止时显式失效。

#### 原版 At 行为

- `卡片`、角色详情/面板、体力、周报、梦魇残声等支持 `命令 @用户` 查询目标用户。
- 多个 At 时采用原版“最后一个有效 At”；忽略机器人自身和全体 At。
- 被查询用户仍受隐私设置约束；日历等全局内容不错误套用用户身份。
- 为 `d卡片@xx`、空格变体、多 At、机器人 At、全体 At、隐私拒绝和管理员场景建立测试矩阵。

#### 更新记录

- 移除聊天内“更新记录”命令及其长 Git log 获取、模板渲染和图片链路，避免超长记录造成渲染与发送负担。
- 更新历史以仓库 `CHANGELOG`/发行说明为唯一长期载体；帮助中不再宣称存在已移除命令。

#### 已知基线问题

- 当前测试基线存在 `test_help_image_is_tracked_and_cleaned` 失败，fake renderer 缺少 `prefix` 参数兼容。正式执行第一阶段时必须先写/确认失败测试，再修复基线，不能把既有失败误归因于新改动。

### 3.2 第二阶段：资源与统一缓存

#### 资源快照与下载

- 公共资源仓库提供基础素材；账号相关私有补充资源单独处理，主插件和资源仓库均不公开发布。
- `ResourceManager` 使用不可变 Git commit 快照：下载到 staging，验证 manifest、路径安全、文件哈希与图片可解码性后，原子切换 active pointer。
- 启动时后台预热，不阻塞插件初始化；管理员命令“下载全部资源”复用并等待同一个 single-flight 任务。
- 角色面板和常用素材应在预热阶段准备，避免首次命令临时逐个下载。

#### 图片获取

- `ImageFetcher` 对连接失败、超时、HTTP 429 与 5xx 做初次请求加 2 次重试，退避 1 秒、2 秒；若响应提供 `Retry-After`，遵循服务端值。
- 404、鉴权失败和结构性响应错误不重试。
- 下载写临时文件，使用 PIL 解码验证后原子替换；同 URL/目标使用 single-flight。
- 失败、空文件和不可解码图片不得进入成功缓存，也不得污染已有完整资源。

#### 统一 CacheManager

- 文件缓存带 sidecar metadata，记录缓存类型、键、内容哈希、创建/访问时间、资源版本、完整性、tags 与租约。
- 查询状态统一为 `fresh`、`stale`、`miss`；过期清理按保留期和租约安全执行。
- 配置默认值：
  - `cache.fresh_ttl_minutes = 30`
  - `cache.retention_ttl_hours = 24`
  - `cache.announcement_ttl_hours = 24`
  - `cache.refresh_send_card = true`
- 角色数据与完整卡片新鲜期 30 分钟、硬保留 24 小时。命中 stale 时先刷新；刷新失败可发送仍完整的旧卡，并明确提示数据可能过期。
- 图片缺失时可以用占位图发送本次卡片，但不向用户显示误导性的“图片丢失”警告；此结果标记 incomplete，不写入/替换完整缓存。
- 帮助菜单只使用进程内缓存；动态资源按内容哈希/资源版本持久化，并由 mark-and-sweep 清理。
- 清理 `rendered/` 孤儿文件和失效租约，解决已观测到约 741 MB 的无界增长，同时不得删除正在发送的文件。

#### 刷新与清理命令

- 普通用户：`刷新<角色名>面板`，仅刷新自己的指定角色数据与卡片。
- 管理员：`刷新<游戏UID>的<角色名>面板`。
- 管理员：`清理全部角色缓存`。
- 刷新成功后由 `cache.refresh_send_card` 控制是否立即发送新卡；刷新必须精准失效指定数据、面板与关联 tags。

#### 公告

- 公告列表/详情需显示完整内容，修复公告无法显示以及只取前 20 条等行为。
- 正确处理查询参数、带 hash 的图片 URL、分页与多图；使用 `MultiImageResponse` 在同一回复中发送所有图片。
- 公告卡片与源图片只有在全部成功时才进入完整缓存。
- 公告缓存采用 24 小时绝对 TTL，并用内容 fingerprint 在上游内容变化时提前失效。
- 上游链接只允许官方来源；URL 校验、下载错误、分页失败必须显式记录真实原因。

### 3.3 第三阶段：AstrBot Agent Tools

#### 注册与总开关

- 配置 `agent_tools.enabled = true` 为唯一总开关；关闭时不注册任何 dnaby 工具。
- `initialize()` 注册工具，`terminate()` 解除注册，热重载后不得出现重复工具或残留 handler。
- 使用 AstrBot 官方 FunctionTool/Agent API，并保持本地 4.27.1 与生产 4.27.4 的兼容性。

#### 允许的工具

- 当前用户玩家概览、角色详情、体力、当前/上期周报。
- 日历、wiki、攻略、兑换码、角色目录。
- 当前梦魇残声、梦魇残声列表、当前用户自己的订阅查看。
- 公告列表与公告详情。
- 签到日历查询。
- 当前用户当前激活 UID 的每日签到。

#### 返回契约与图片

- 默认只向 Agent 返回结构化 JSON：`ok`、`kind`、`data`、`cache`、`error`。
- 身份只从 `AstrAgentContext.event` 提取，工具参数中不接受可伪造的用户身份。
- 支持图片的工具提供可选 `send_image=false`；为 `true` 时图片直接发送给当前用户，Agent 只获得 `image_sent` 等结构化结果，不把本地路径或二进制塞入模型上下文。

#### 签到安全

- 只有原始用户消息匹配明确肯定意图且不含否定表达时才允许签到；模型不能通过布尔参数伪造确认。
- 同一消息 ID 幂等，避免工具重试导致重复签到。
- 仅允许当前用户、当前激活 UID；失败区分未绑定、凭据过期、网络失败、上游拒绝与已签到。

## 4. 生产环境定向热重载可行性

### 4.1 只读探查结论

结论：**可行**，但执行时必须先通过已认证的 Dashboard API 做插件 ID 预检；本轮没有实际重载。

生产现状（2026-08-28 只读观测）：

- 主机别名：`atri`。
- AstrBot 根目录：`/srv/AstrBot`；插件目录：`/srv/AstrBot/data/plugins/astrbot_plugin_dnaby`。
- Docker 容器名：`astrbot`，镜像 `soulter/astrbot:latest`，AstrBot 版本日志显示 4.27.4。
- Dashboard 端口 6185 已映射；另有 6199、10000。
- 插件仓库干净，分支 `main` 跟踪 `origin/main`；探查时 SHA 为 `9a33b60ed3545020b97acb11e18b91041c1f80de`。
- `StarManager.reload(specified_plugin_name)` 会在 `_pm_lock` 下终止指定插件、解绑 handler/实例并重新加载指定模块，不要求重启整个 AstrBot。
- Dashboard 路由存在 `POST /api/v1/plugins/{plugin_id}/reload`，要求 `plugin` scope，内部调用 `PluginService.reload_plugin({"name": plugin_id})` 并在失败时返回显式错误。
- 登录入口为 `POST /api/v1/auth/login`，请求字段为 `username`、`password`；生产配置存在 Dashboard 用户、密码哈希、JWT secret 与端口配置。本计划不得读取或打印其值。

代码证据位于生产容器中的：

- `astrbot/core/star/star_manager.py`：`StarManager.reload`。
- `astrbot/dashboard/api/plugins.py`：插件 reload endpoint。
- `astrbot/dashboard/services/plugin_service.py`：`PluginService.reload_plugin`。
- `astrbot/dashboard/api/auth.py` 与 `astrbot/dashboard/schemas.py`：Dashboard JWT/登录契约。

由于本轮被明确限制为只读探查，没有发送重载 POST，也没有用生产凭据登录。可行性由正在运行的 4.27.4 源码、端口映射、插件状态与鉴权配置共同确认；真正部署任务仍必须完成一次受控预检和回滚演练。

### 4.2 每阶段部署与热重载步骤

以下步骤只在用户明确启动目标、对应阶段本地门禁通过且得到该阶段 commit SHA 后执行：

1. **记录恢复点**：记录当前部署 SHA、插件目录 clean 状态、插件 activated 状态、日志起点、资源 active pointer 与当前配置摘要；不得记录任何凭据值。
2. **确认插件 ID**：通过已认证的 `GET /api/v1/plugins` 或 `GET /api/v1/plugins/{plugin_id}` 确认目标 ID 确为 `astrbot_plugin_dnaby`、状态正常且当前凭据具备 `plugin` scope。未确认不得调用 reload。
3. **准备目标 SHA**：在服务器插件仓库执行非破坏性的 `git fetch --prune origin`，验证目标 commit 存在且来源正确；工作树非 clean 时停止，不覆盖生产现场改动。
4. **切换精确版本**：检出计划中记录的精确 commit SHA，不部署漂移的分支头；再次核对 `HEAD`、metadata 版本与生成投影。
5. **服务器预检**：运行最小 `compileall`、目标测试/导入检查以及配置 schema 检查。任何失败都在重载前回到原 SHA 并停止。
6. **调用定向重载**：使用本机回环地址和安全注入的 JWT/API key 调用 `POST http://127.0.0.1:6185/api/v1/plugins/astrbot_plugin_dnaby/reload`。凭据不得出现在 shell history、进程参数、日志或计划文件。
7. **判定 API 结果**：同时要求 HTTP 成功、响应业务状态成功和“重载成功”语义；不能仅凭 2xx 判定完成。
8. **核对生命周期**：检查从记录的日志起点开始，旧实例只终止一次，新实例只初始化一次；scheduler、公告任务、handler、缓存清理循环和 Agent Tools 均不得重复注册或残留。
9. **核对运行状态**：再次 GET 插件状态，确认 activated、插件版本与服务器 `HEAD` 一致；检查无新增 traceback、资源 active pointer 未损坏。
10. **阶段验收**：运行 AstrBot adapter 模拟的命令/权限/At/缓存/工具 E2E；将生成图片安全复制回本地，由 Agent 使用图片查看能力检查公告、帮助、面板和多图回复。
11. **失败回滚**：任一步失败，检出第 1 步记录的原 SHA，再调用同一个定向 reload endpoint；重复生命周期与冒烟检查，确认恢复。
12. **停止条件**：若 API 鉴权、插件 ID、reload endpoint、回滚 SHA 或工作树状态不能确认，则标记部署阻塞并停止。不得自行重启容器或执行 `git reset --hard`。

### 4.3 分阶段部署约束

- 阶段一、二、三各自形成独立 SHA，依次部署、热重载和验收；不得把三个阶段压成一次不可分割更新。
- 第二阶段先提交并验证公共资源仓库的对应 commit，再提交引用该资源版本的插件 SHA。
- 每阶段重载失败都回滚到上一已验收 SHA；后续阶段不得越过失败阶段继续部署。
- 容器重启仅能作为用户另行明确授权的恢复动作，不属于本计划正常路径。

## 5. 测试与质量门禁

- 所有代码改动严格使用 `tdd` skill：Red → Green → Refactor；Red 必须实际运行并因目标行为失败。
- 最小目标测试之后运行相关集成测试，再执行：
  - `python3 -m pytest`
  - `ruff check .`
  - `python3 -m compileall .`
- 修改 registry、配置或命令时重新生成并核对 `commands.json`、`_conf_schema.json`。
- 修改命令、配置、资源、缓存或 Agent Tools 时同步 `docs/usage/`、`docs/project/` 及必要的开发文档。
- 每阶段交付前做自审并使用 `code-review-expert`；阻塞问题修复后重新验证。
- AstrBot adapter 模拟需覆盖普通用户/管理员、At 目标、隐私、缓存 fresh/stale/miss、不完整图片、公告多图、热重载生命周期和 Agent tool 重复注册。
- 图片验收必须打开实际产物检查，不以文件存在或 PIL 可解码替代视觉检查。
- 生产 target 为 4.27.4，本地兼容基线为 4.27.1；公共接口差异需显式适配和测试。

## 6. 数据与安全不变量

- 所有运行期数据只能写入 `StarTools.get_data_dir(self.name)`：数据库、订阅、公告状态、渲染、角色自定义面板、资源与缓存均不得写入插件源码目录。
- 缓存不缓存失败，不以空结果冒充成功，不吞下载/渲染/API/清理异常。
- 资源路径必须防目录穿越，manifest 与哈希验证失败不得激活。
- 发送中的文件由租约保护；清理器不得删除在用文件。
- 生产部署只允许精确 SHA、可验证 reload、可验证回滚；不使用 `git reset --hard`。

## 7. 交付完成定义

只有以下条件全部有证据时，整个目标才可完成：

- 三个阶段的行为、配置、命令清单、文档与测试全部落地。
- 公告、帮助、At 查询、资源预热、统一缓存、刷新命令和 Agent Tools 的验收矩阵全部通过。
- 完整/不完整图片缓存规则、过期清理与租约经测试证明。
- 三个独立插件 SHA 及资源 SHA 可追溯。
- 每阶段在 `atri` 通过定向热重载和 adapter 模拟验收，且拥有验证过的回滚证据。
- 全量 pytest、ruff、compileall 和代码审查无本次变更相关阻塞项。
- 未泄露或提交任何生产秘密与运行期数据。
