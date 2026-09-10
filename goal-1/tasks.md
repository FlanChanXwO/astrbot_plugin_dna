# Goal 1 任务清单

状态约定：`[ ]` 未完成，`[x]` 已完成。每个任务完成后必须填写“实际变更、验证证据、剩余风险、下一步”。

## Task 1：建立运行期数据布局接口与测试基线

- 状态：[x]
- 范围：新增统一 `RuntimeDataLayout` 及对应路径测试；明确数据根、数据库、状态、资源、缓存和备份路径。
- 验收：新路径可被构造；测试明确 `db/dna.sqlite3`、`state/aliases`、资源和缓存子域。
- 实际变更：新增 `src/infrastructure/data_layout.py`，提供只读运行期数据根、`db/dna.sqlite3`、`state/`、`resources/`、`cache/`、`backups/` 路径接口；从 `src.infrastructure` 导出 `RuntimeDataLayout`；新增路径契约测试。
- 验证证据：Red 阶段测试因 `RuntimeDataLayout` 尚未导出而失败；实现后 `tests/test_runtime_data_layout.py` 与 `tests/test_persistence.py` 共 10 项通过；目标文件 Ruff 检查通过；目标文件 `compileall` 通过；LSP 对 3 个变更文件无诊断。
- 剩余风险：布局尚未接入 bootstrap、数据库、legacy detector 和各业务状态/缓存路径，留待后续任务；当前测试环境需存在空的 `tests/.data` 目录，属于现有 fixture 环境问题。
- 下一步：执行 Task 2，实现启动前 legacy layout detector 与 fail-fast。

## Task 2：实现 legacy layout detector 与启动前 fail-fast

- 状态：[x]
- 范围：检测旧数据库、旧 resource/generation、旧状态、旧 rendered/other、旧 cache 和 `resources/.git` 旧形态；确保检测早于任何新目录或数据库写入。
- 验收：旧结构明确失败并包含迁移提示；新结构通过；无自动复制、移动或双读。
- 实际变更：新增 `LegacyLayoutDetector`、`LegacyLayoutIssue` 和 `LegacyLayoutError`，覆盖旧数据库、资源、状态、渲染、媒体、缓存及旧资源仓库标记；旧目录仅在含实际数据时阻断，`resources/.git` 始终作为旧仓库位置阻断，避免导入期空目录副作用误报。`build_runtime` 在真实数据库构造前解析 `RuntimeDataLayout` 并执行只读门禁，错误明确要求人工迁移/清理且声明不自动复制、移动或双读；从 `src.infrastructure` 导出 detector API。新增逐路径、空新布局、无变更和启动前数据库创建顺序测试。
- 验证证据：Red 阶段新增测试先因 detector 尚未导出/接入而失败；实现后 `tests/test_legacy_layout.py` 23 项通过，路径、持久化、配置相关测试共 50 项通过；目标文件 Ruff 检查通过；`src` 与 `tests` `compileall` 通过；LSP 对 bootstrap、detector、基础设施导出和测试文件均无诊断。
- 剩余风险：旧 `RESOURCE_PATH` 导入期副作用和旧数据库实际路径仍待 Task 3 清除/切换；混合回归中的既有登录页面断言失败与 goal 工作区守卫失败未归属于本任务，本轮未修改其相关行为。
- 下一步：执行 Task 3，移除旧路径导入期副作用并切换数据库到 `db/dna.sqlite3`。

## Task 3：消除旧路径导入期副作用并切换数据库路径

- 状态：[x]
- 范围：移除旧 `RESOURCE_PATH`/`name_convert` 导入期创建副作用；数据库改为 `db/dna.sqlite3`；保留别名业务能力但改由 layout 提供路径。
- 验收：导入模块不创建旧目录；数据库初始化只写新路径；别名调用方仍可工作。
- 实际变更：移除两个 `RESOURCE_PATH` 模块的导入期目录创建；将兼容模块改为无副作用路径投影；新增 `RuntimeDataLayout` 的 `state/aliases/{char,weapon,id2name}.json` 契约；`name_convert` 改为按需创建并写入别名目录，bootstrap 统一绑定实际 layout；`AsyncDatabase.from_data_dir()` 改用 `db/dna.sqlite3` 并在数据库初始化阶段创建 `db/`；修正 bootstrap 在新数据库路径下对数据根、别名和现有状态路径的推导。
- 验证证据：Red 阶段目标测试 `6 failed, 8 passed`；Green 阶段 `tests/test_runtime_data_layout.py tests/test_persistence.py tests/test_name_convert.py tests/test_config.py::test_build_runtime_propagates_all_settings` 为 `14 passed`；别名、资源、登录媒体、渲染相关测试 `32 passed`；`compileall src tests`、目标文件 Ruff、`git diff --check` 通过；LSP 对受影响源码无诊断，引用分析确认 `configure_alias_storage` 仅由 bootstrap 调用并保留测试覆盖。
- 剩余风险：完整 pytest 为 `240 passed, 7 failed`；7 项均为本任务前已存在或与本任务无关的签到、命令前缀、登录页面、goal 工作区守卫和玩家详情断言失败，未修改其行为。全仓 Ruff 仍有 24 项既有违规；目标文件 Ruff 已通过。资源 repository/generation、动态缓存和 state 目录的最终归位留待 Task 4-6。
- 下一步：执行 Checkpoint 1，集中复查 Task 1-3 的路径引用、启动顺序和回归证据。

## Checkpoint 1：集中检查路径切换

- 状态：[x]
- 范围：复查 Task 1-3 的 diff、引用和启动顺序；运行路径、持久化和别名相关测试。
- 验证证据：复查 `1ab4515..HEAD` 共 3 个 task commit，`git diff --check` 通过；LSP 引用确认 `AsyncDatabase.from_data_dir()` 调用点为 bootstrap、live 脚本和持久化测试，`RuntimeDataLayout` 已接入 bootstrap、数据库和别名模块；启动顺序保持为解析 layout、只读 `LegacyLayoutDetector.ensure_compatible()`、再创建数据库；路径、legacy、持久化、配置、别名和 Dashboard 测试共 `62 passed`；受影响源码 LSP 诊断为空。
- 发现问题与修复：未发现 Task 1-3 范围内的新问题，未扩大修改范围。确认 `resource_generations`、顶层 `rendered`/`other`、旧状态文件和动态缓存引用仍属于后续 Task 4-6 的待迁移项；当前未将其误标为已完成。
- 剩余风险：Task 4-6 尚未统一资源 repository/generation、缓存、state 和备份路径；全量 pytest 与全仓 Ruff 的既有失败已记录在 Task 3，不影响本 checkpoint 的路径/持久化/别名证据。
- 下一步：执行 Task 4，切换公共资源 repository 与 generation 路径，同时保持 generation 校验、原子发布和 lease 边界。

## Task 4：切换公共资源 repository 与 generation 路径

- 状态：[x]
- 范围：将资源工作树切到 `resources/repository/`，generation 切到 `resources/generations/`，保留 manifest 校验、原子发布和 lease。
- 验收：全新数据目录同步并发布 generation；同步期间旧 generation 可读；新 repository `.git` 不触发 legacy guard。
- 实际变更：扩展 `RuntimeDataLayout`，统一提供 `resources/repository/`、`resources/generations/` 及 `current.json`、`last_sync.json`、`validation.json` 路径；资源 path helper 和兼容常量改为委托统一 layout；bootstrap 的 `ResourceSnapshotCoordinator` 与 `ResourceUpdateService` 改用新 repository/generation 路径。新增嵌套路径契约测试，并将新 repository `.git` 夹具改为由 layout 构造。未改动现有 manifest 校验、候选物化、原子指针发布和 lease 回收逻辑。
- 验证证据：Red 阶段 `tests/test_runtime_data_layout.py -q` 为 `2 failed, 1 passed`，失败来自尚未实现的嵌套资源路径契约；Green 阶段 `tests/test_runtime_data_layout.py tests/test_legacy_layout.py tests/test_resources.py tests/test_config.py -q` 为 `50 passed`。注入 fake Git/validator 的 generation smoke 验证全新目录 clone、两次 generation 发布、`current.json` 指针、旧 lease 持有期间旧 generation 可读、释放后回收，以及 `resources/repository/.git` 不触发 legacy guard。完整 pytest 为 `241 passed, 7 failed`，失败仍是既有签到、命令前缀、登录页面、goal 工作区守卫和玩家详情断言；目标文件 Ruff、`compileall src tests`、`git diff --check` 通过；LSP 对受影响源码无诊断。
- 剩余风险：Task 5-6 仍待迁移动态缓存、state 和备份路径；全仓 Ruff 的既有违规与完整 pytest 的 7 项既有失败未在本任务扩大范围内处理。资源 generation 仍由现有 validator 执行完整内容校验，真实远端同步需在部署环境验证。
- 下一步：执行 Task 5，切换动态素材、API、渲染和媒体缓存路径。

## Task 5：切换动态素材、API、渲染和媒体缓存路径

- 状态：[x]
- 范围：迁移 `resource/*` 到 `cache/assets/*`，拆分游戏头像和用户头像，迁移 API、玩家卡、MH、顶层 rendered 和 other 媒体路径。
- 验收：新运行不会创建顶层 `resource/`、`rendered/` 或 `other/`；缓存读写和清理语义保持不变。
- 实际变更：扩展 `RuntimeDataLayout`，提供 `cache/assets`、`cache/api`、`cache/rendered`、`cache/media` 及游戏头像、用户头像、自定义素材、签到、公告、日历和登录二维码子目录；更新资源路径兼容投影与用户头像调用方，登录二维码改用新媒体目录；bootstrap 将玩家数据、玩家卡、密函和公告 typed cache 映射到对应 cache namespace，并统一把渲染与百科临时产物放入 `cache/rendered`。`CacheManager` 的 sidecar、完整性、租约、TTL、invalidate 和递归清理语义保持不变。
- 验证证据：Red 阶段 Task5 目标测试先得到 `4 failed, 3 passed`；补充登录二维码路径契约后实际得到 `1 failed, 19 passed`。Green 阶段 `tests/test_runtime_data_layout.py tests/test_legacy_layout.py -q` 为 `31 passed`；相关资源、渲染、缓存和签到回归为 `87 passed, 3 failed`，3 项为既有玩家详情/签到断言失败；最终完整 pytest 为 `248 passed, 5 failed`，新增失败均未出现，剩余失败为既有签到、登录集成、goal 工作区守卫和玩家详情断言。目标文件 Ruff、`compileall src tests`、`git diff --check` 通过；LSP 诊断为空；源码检索未发现旧顶层 `resource`、`rendered`、`other` 或 `login_qr` 写入构造。
- 剩余风险：完整 Ruff 仍受本任务前的仓库既有违规影响；Task 6 仍需迁移 state、aliases 和备份路径，Task 7-11 尚未执行。未显式提供 namespace 映射的独立 `CacheManager` 继续使用原有 `cache/<type>` 物理布局，这是为保持现有调用方兼容；生产 bootstrap 已提供完整映射。
- 下一步：执行 Task 6，迁移 state、aliases 与备份路径。

## Task 6：迁移 state、aliases 与备份路径

- 状态：[x]
- 范围：迁移订阅、调度、公告、客户端更新、角色/武器别名和状态迁移备份；所有路径由统一 layout 注入。
- 验收：状态可读写；别名命令、Dashboard 和 loadout 仍工作；备份写入 `backups/`，不在数据根产生旧旁车。
- 实际变更：`RuntimeDataLayout` 新增 `state/subscriptions.json`、`state/scheduler.json`、`state/announcements/{seen,delivery}.json`、`state/client_update.json` 及 `backups/{database,state}/` 契约；bootstrap 将订阅、调度、公告和客户端更新状态统一注入这些路径，并继续注入 `state/aliases/{char,weapon}.json`；`ClientUpdateStateStore` 支持显式迁移备份路径，生产迁移原始字节写入 `backups/state/client_update.json.v2.bak`；公告服务的隐式投递状态路径改为与 `seen.json` 同目录的 `delivery.json`。
- 验证证据：Task 6 Red 目标测试实际为 `4 failed, 5 passed`（缺少新布局属性）；Green `tests/test_runtime_data_layout.py -q` 为 `9 passed`；相关状态、公告、调度、Dashboard、别名和配置回归为 `98 passed, 1 warning`；完整 pytest 为 `250 passed, 5 failed`，失败仍为既有签到 2 项、登录集成 1 项、goal 工作区守卫 1 项、玩家详情 1 项，未新增本任务失败；目标源码 Ruff、格式、`compileall src tests`、`git diff --check` 通过；5 个受影响文件 LSP diagnostics 均为空。
- 剩余风险：完整 pytest 的 5 项既有失败仍待后续任务/最终审查归属；`ClientUpdateStateStore` 的无显式参数构造仍保留同文件旁车默认值，仅生产 bootstrap 注入 `backups/state`，避免破坏独立调用方测试；未在本任务清理 legacy detector 中有意保留的旧路径标记或独立兼容 API 的可选 fallback。
- 下一步：执行 Checkpoint 2，集中检查生产目录重构与全仓旧路径引用。

## Checkpoint 2：集中检查生产目录重构

- 状态：[x]
- 范围：运行持久化、调度、公告、Dashboard、资源和玩家测试；检查全仓旧路径引用、生成目录和迁移映射完整性。
- 验证证据：布局探针确认 `db/dna.sqlite3`、`state/{subscriptions,scheduler,client_update}.json`、`state/announcements/{seen,delivery}.json`、`state/aliases/{char,weapon}.json`、`resources/{repository,generations}`、`cache/{assets,api,rendered,media}` 和 `backups/{database,state}`；构造布局不创建数据根；legacy marker 共 23 项。持久化、调度、公告、Dashboard、资源、玩家、别名及布局回归合计 `103 passed, 1 failed, 1 warning`，唯一失败为既有 `tests/test_player.py::test_role_detail_renders_all_basic_sections_and_original_path` 的额外“伤害” section 断言；额外百科、渲染、登录媒体测试 `34 passed, 1 warning`；`ruff check src tests`、`compileall .`、`git diff --check` 通过；LSP 引用/影响面审计完成，受影响源码 diagnostics 为空。
- 发现问题与修复：全仓旧路径命中均已分类：`legacy_layout.py` 中是启动门禁标记，CHANGELOG/Alembic/数据库与状态模块 docstring 是历史或迁移说明，别名与百科模块的旧文件名仅为独立 API 的可选 fallback，生产 bootstrap 已显式注入 `state/aliases`；资源 generation、cache namespace 和 state 注入均无遗漏。未发现需在本 checkpoint 修复的生产路径问题。
- 剩余风险：既有玩家详情断言仍失败；`AdminAliasService`/`EncyclopediaResourceStore` 的独立调用默认 fallback 与 `src/utils/subscriptions.py` 的遗留全局兼容模块仍含旧命名，但没有活动 bootstrap 调用；后续任务仍需实现 AssetResolver、共享下载器、渲染并发、迁移文档和最终审查。
- 下一步：执行 Task 7，实现 generation-first `AssetResolver`。

## Task 7：实现 generation-first AssetResolver

- 状态：[x]
- 范围：引入素材类型映射和 L1/L2/下载决策；接入当前 generation lease；先覆盖头像、立绘和武器图。
- 验收：L1 命中时零网络且不复制 L2；L1 缺失时命中 L2；双 miss 才下载；L1 损坏不被覆盖。
- 实际变更：
  - 新增 `src/infrastructure/resources/resolver.py`，统一解析 `role_avatar`、`role_paint`、`weapon` 三类素材。
  - L1 读取当前已验证 generation 的公共路径；L2 使用 `cache/assets/{game_avatar,paint,weapon}` 的现有动态缓存契约；双 miss 才调用注入下载器，且下载目标仅为 L2。
  - 对 L1/L2 做普通文件、路径边界和完整图片校验；损坏 L1 保持只读，损坏 L2 清理后再按需下载。
  - `ResourceSnapshotCoordinator.bind_asset_resolver()` 在 generation lease 内固定当前快照；bootstrap 暴露 `asset_resolver` service，并允许测试/宿主注入替代实现。
- 验证证据：
  - Red：新增 bootstrap 集成断言前运行对应测试，因缺少 `asset_resolver` service 以 `KeyError` 失败；resolver 初始测试因模块不存在以 `ModuleNotFoundError` 失败。
  - Green：`python -m pytest tests/test_asset_resolver.py tests/test_runtime_data_layout.py tests/test_resources.py -q`，`21 passed, 1 warning`。
  - `ruff check`、`ruff format --check`、`python3 -m compileall`、`git diff --check` 通过；受影响源码和测试 LSP diagnostics 为空。
- 剩余风险：Task 8 将替换当前 resolver 对 legacy `image_utils.download` 的默认调用，接入共享 client、URL 级合并和生命周期关闭；Task 9 前现有 renderer 仍直接使用旧图片入口，resolver 尚未成为渲染路径。
- 下一步：执行 Task 8，改造共享自适应图片下载器。

## Task 8：改造共享自适应图片下载器

- 状态：[x]
- 范围：长生命周期 AsyncClient、动态容量、AIMD 退避、Retry-After、URL 级 inflight、不同 target fan-out、原子写入和 lifecycle hook。
- 验收：同 URL 只产生一次真实请求；不同 URL 正常并发；失败和取消语义明确；stop/reload 无 client 或任务泄漏。
- 实际变更：
  - `ImageFetcher` 改为每个 runtime 共享的长生命周期 `AsyncClient`，新增 `start()/close()`，关闭期间拒绝新网络下载，等待 active 请求自然完成后释放 client，并支持 reload 后重新启动；legacy `download()` 默认入口在 bootstrap 中指向当前 runtime 实例。
  - 新增不暴露给用户配置的条件并发容量：429 立即 AIMD 收缩，5xx/传输错误累计后收缩，连续健康请求逐步恢复；默认 HTTP 连接池内部硬上限为 64。
  - inflight key 改为完整 URL；共享任务只下载并校验一次 bytes，再向不同 target fan-out，各 target 继续使用临时文件校验和 `os.replace` 原子写入；单个 waiter 取消不会取消共享请求。
  - bootstrap 注入共享 `image_fetcher` 到 `AssetResolver`，挂接 lifecycle start/finalizer close；补充运行期 service、生命周期、并发、重试、Retry-After、失败、取消、drain/reload 回归测试。
- 验证证据：
  - Red：新增下载器测试先因 `ImageFetcherClosed` 尚不存在而收集失败；runtime 集成断言先因缺少 `image_fetcher` service 以 `KeyError` 失败。
  - Green：`python -m pytest tests/test_image_fetcher.py -q` 为 `10 passed, 1 warning`；下载器、resolver、资源、runtime layout 和默认 lifecycle 集成回归合计 `32 passed, 1 warning`。
  - 扩大到完整 `tests/test_integration.py` 后为 `48 passed, 2 failed`；两项失败均为既有的登录页面文案断言和 goal 工作区守卫，不由本任务改动引入。
  - 受影响源码/测试 LSP diagnostics 为空；目标 Ruff、格式检查、`compileall -q src tests` 与 `git diff --check` 通过。
- 剩余风险：现有 renderer 仍直接使用 legacy 图片入口，统一 resolver 和渲染前并发准备留给 Task 9；resolver 的独立调用仍保留 legacy fallback，但生产 bootstrap 已注入共享下载器。
- 下一步：执行 Task 9，并在同一 generation lease 内并发准备角色详情素材。

## Task 9：并发准备角色详情素材并保持渲染契约

- 状态：[x]
- 范围：在单一 generation lease 内并发技能、角色 Mod、武器、属性和立绘相关素材；按原业务顺序组装 payload。
- 验收：冷缓存不再逐项串行等待；无武器、特殊武器、多 Mod 和同 URL 多业务 ID 场景通过；占位和展示顺序不变。
- 实际变更：
  - 玩家总览与详情渲染在同一 generation lease 内并发准备头像、立绘、属性、技能、角色 Mod、武器及武器模式素材；使用有序 `gather` 组装 payload，保留原业务顺序、占位和空武器行为。
  - `PlayerRenderer` 接入绑定的 `AssetResolver`，角色头像/立绘/武器走 generation L1、动态缓存和下载链路；技能、Mod、属性继续复用既有 loader 语义，保留 legacy fallback。
  - 武器详情支持并发加载武器图和多 Mod，同时由 `ResourceSnapshotCoordinator.bind_renderer` 共享同一 generation lease，避免渲染过程中 resolver 与资源视图跨 generation。
  - 新增并发、顺序和 resolver 复用回归测试。
- 验证证据：
  - Red：新测试先实际得到 `2 failed`：素材加载最大并发仍为 `1`，且详情渲染尚不接受 `asset_resolver` 参数。
  - Green：目标回归命令 `python -m pytest tests/test_player_asset_prefetch.py tests/test_asset_resolver.py tests/test_image_fetcher.py tests/test_resources.py tests/test_runtime_data_layout.py tests/test_integration.py::test_default_runtime_login_handler_returns_live_local_url -q` 为 `35 passed, 1 warning`。
  - `ruff check`（所有变更源码和测试）、`ruff format --check`（本任务新增/改动的 5 个格式化文件）、`python3 -m compileall -q src tests`、`git diff --check` 通过；受影响文件 LSP diagnostics 为空。
  - 相关 `tests/test_player.py` 当时仍有 2 项已知非本任务阻塞：全局 ImageFetcher 在 pytest 多 event loop 下的 `Event loop is closed` 不稳定失败，以及既有详情断言未计入 `伤害` 区块；前一项已在 Checkpoint 4 为 runtime 生命周期修复，后一项仍是基线断言差异，目标回归不受影响。
- 剩余风险：技能、角色 Mod、属性仍使用既有动态 loader；只有角色头像/立绘/武器已接入统一 resolver。runtime 下载器的 event loop 生命周期问题已在 Checkpoint 4 修复，进程级 legacy 入口仍保留兼容 fallback。
- 下一步：执行 Checkpoint 3，集中检查 resolver、downloader、generation、player rendering 的并发、取消、lease 和 cache 原子性。

## Checkpoint 3：集中检查资源流水线

- 状态：[x]
- 范围：运行 resolver、downloader、generation、player rendering 的完整相关测试；复查并发取消、lease 和 cache 原子性。
- 验证证据：
  - Red：新增跨类别并发断言实际失败（`cross_category_overlap == False`），定位到武器区块在详情渲染中先完整 `await`，尚未与立绘、技能和其他素材重叠准备。
  - Green：修复后 `tests/test_player_asset_prefetch.py` 为 `2 passed, 1 warning`；resolver、downloader、资源同步与新增渲染回归合计 `25 passed, 1 warning`。
  - 扩展相关套件（resolver、downloader、resources、runtime layout、legacy layout、player rendering、integration）为 `94 passed, 5 failed, 1 warning`；失败均已定位并记录，未发现资源解析、下载器取消/排空、generation lease 或缓存原子写入的新失败。
  - `ruff check`、`ruff format --check`、`python3 -m compileall -q src tests`、`git diff --check` 通过；受影响源码和测试 LSP diagnostics 为空。
- 发现问题与修复：
  - 将 `weapon_sections` 从提前等待改为与 header、hero、技能、角色魔之楔和属性图标共同进入一次 `asyncio.gather`；`gather` 返回值仍按原武器标题顺序组装，保留空武器和特殊武器行为。
  - 相关套件剩余失败：全局 `ImageFetcher`/`AsyncClient` 在 pytest 多 event loop 间复用导致的 `Event loop is closed`（玩家凭据测试及 runtime terminate）；既有详情测试未把 `伤害` 区块计入期望顺序；两项登录页面旧文案断言；以及活动 goal 工作区守卫与当前 `goal-1/` 工作文件冲突。均非本 checkpoint 的资源流水线回归。
- 剩余风险：进程级 legacy 图片入口在未绑定 runtime 的独立调用场景仍保留兼容行为；runtime 生命周期的跨 event loop 复用问题已在 Checkpoint 4 修复。登录页面断言和 goal 工作区守卫属于已有测试/工作流问题。资源流水线核心的 L1/L2 优先级、URL fan-out、取消排空、generation lease 和原子缓存写入已有目标测试覆盖。
- 下一步：执行 Task 10，补齐手动迁移文档与发布说明。

## Task 10：编写手动迁移文档与发布说明

- 状态：[x]
- 范围：更新 `docs/usage/resources.md` 和 `CHANGELOG.md`，记录停机备份、旧到新映射、可不迁移缓存、别名迁移和旧目录清理。
- 验收：文档不包含真实部署路径、凭据或固定测试数量；用户能按文档完成手动迁移和回滚。
- 实际变更：
  - 在资源文档中补充现行 `db/`、`state/`、`resources/`、`cache/`、`backups/` 布局，以及停机备份、逐项映射、别名合并、缓存可跳过、旧标记清理、启动验证和回滚步骤。
  - 在 `CHANGELOG.md` 增加 Unreleased 发布说明，明确旧布局拒绝、人工迁移和资源/缓存分层行为。
- 验证证据：
  - `git diff --check` 通过。
  - 文档专项脚本确认必要章节、数据库/别名/generation/缓存映射存在，且未出现真实部署路径、凭据样式或固定测试数量。
- 剩余风险：
  - 旧数据库双文件选择、别名冲突合并和 generation 兼容性仍需部署者依据备份人工确认；代码按设计不执行自动迁移或自动回滚。
- 下一步：执行 Task 11，完成全量验证与交付审查。

## Task 11：全量验证与交付审查

- 状态：[x]
- 范围：运行相关测试、完整 pytest、ruff、compileall；检查 Git diff、旧路径残留、生成物和提交拆分。
- 验收：所有可归属失败已修复或明确记录；不存在未验证的验收条件；保留用户已有无关改动。
- 实际变更：
  - 完成目标相关回归、全量测试、静态检查、LSP 诊断、旧路径/生成物和提交拆分审计。
  - 审计发现 runtime 默认下载器跨 pytest event loop 复用连接池会在终止时失败；先加入 runtime 间下载器隔离回归测试并确认 Red，再让每个未显式注入下载器的 runtime 创建并持有自己的 `ImageFetcher`，保留注入服务的宿主/测试替换能力。
- 验证证据：
  - Red：新增 `test_build_runtime_allocates_image_fetcher_per_runtime` 在项目 `.venv` 中实际因两个 runtime 复用同一 `ImageFetcher` 失败；Green 后该测试通过。
  - 使用项目 `.venv` 的 Python 3.12.13 运行资源流水线目标套件：`tests/test_asset_resolver.py`、`tests/test_image_fetcher.py`、`tests/test_player_asset_prefetch.py`、`tests/test_runtime_data_layout.py`、`tests/test_legacy_layout.py`、`tests/test_resources.py`，结果为 `59 passed, 1 warning`。
  - 使用同一 `.venv` 运行完整 `pytest -q`，结果为 `269 passed, 5 failed, 1 warning`。剩余失败为两项自动签到旧语义断言、本地登录页旧标题断言、活动 goal 工作区守卫与当前 `goal-1/` 工作文件冲突，以及既有详情区块断言遗漏 `伤害`；5 项均在基线 `e79ff6e` 的完整套件中复现（基线为 `250 passed, 5 failed, 1 warning`），未形成资源流水线新增失败。
  - `ruff check .`、`.venv/bin/python -m compileall -q src tests`、`git diff --check`（含 `e79ff6e..HEAD`）通过。`ruff format --check .` 仍报告基线中已有的 15 个文件；本任务新增/修改的 `src/bootstrap.py` 与 `tests/test_runtime_data_layout.py` 已格式化，既有变更文件 `src/modules/player/service.py` 在基线同样未通过格式检查，未为本任务扩大范围。
  - 受影响源码和测试 LSP diagnostics 为空；`git status --short --branch` 清洁。`e79ff6e..HEAD` 的提交按任务拆分，文件仅覆盖资源布局、resolver、下载器、渲染、测试、文档和 goal 记录；`commands.json`、`_conf_schema.json` 未被修改。旧路径命中仅限 legacy detector、迁移文档、显式兼容别名投影和既有测试夹具，新 bootstrap 路径已切换到新布局。
- 剩余风险：
  - 进程级 legacy `download()` 兼容入口仍保留未绑定 runtime 的默认下载器；生产 bootstrap 已将其切换为 runtime 自有共享下载器，插件正常单事件循环路径已覆盖。手动迁移中的数据库双文件选择、别名冲突和 generation 兼容性仍由部署者依据备份确认，代码不自动迁移或回滚。
- 下一步：
  - Checkpoint 4 已完成；goal 已具备结束条件。

## Checkpoint 4：最终集中检查与停止条件

- 状态：[x]
- 范围：对全部任务、验收标准、测试证据和回滚说明做逐项审计；只有证据完整才允许标记 goal 完成。
- 验证证据：
  - Task 1-6：`RuntimeDataLayout` 已统一 `db/`、`state/`、`resources/`、`cache/`、`backups/`；数据库为 `db/dna.sqlite3`；legacy detector 在数据库构造前只读 fail-fast，测试覆盖旧标记、空新布局和无迁移副作用。
  - Task 7：`AssetResolver` 在 generation lease 中按角色头像、角色立绘、武器执行 L1 当前 generation → L2 动态缓存 → 网络下载，命中和损坏资源的优先级/只读边界由目标测试覆盖。
  - Task 8：runtime 共享 `ImageFetcher` 已具备长生命周期 `httpx.AsyncClient`、动态并发、Retry-After/AIMD、完整 URL inflight 合并、不同 target fan-out、取消隔离、原子校验写入和 stop/reload drain；目标套件与 runtime 隔离回归均通过。
  - Task 9：玩家角色详情素材在同一 generation lease 内并发准备，结果按原业务顺序组装，空武器、特殊武器、多 Mod、占位和错误语义测试通过。
  - Task 10-11：手动迁移/回滚文档和 `Unreleased` 发布说明已完成；静态检查、LSP、全量 diff、旧路径分类、生成投影和提交拆分已审计。
  - 代码提交序列为每个实施 task/修复独立提交，当前分支工作树清洁；未覆盖无关用户改动。
- 未满足项：
  - Goal 范围内无未满足项。完整套件仍保留 5 项基线/工作流失败，详见 Task 11；`ruff format --check .` 的 15 个既有格式问题也未扩大处理。它们不属于本 goal 的资源布局与流水线验收条件。
  - 生产升级仍要求部署者先停机备份、人工迁移并按文档验证；这是已确认的 breaking-change 运维边界，不由代码自动完成。
- 下一步：
  - 全部任务和验收条件已有证据，goal 可标记完成；后续若需处理基线测试或 legacy 兼容入口，应另开独立任务。
