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

- 状态：[ ]
- 范围：迁移订阅、调度、公告、客户端更新、角色/武器别名和状态迁移备份；所有路径由统一 layout 注入。
- 验收：状态可读写；别名命令、Dashboard 和 loadout 仍工作；备份写入 `backups/`，不在数据根产生旧旁车。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Checkpoint 2：集中检查生产目录重构

- 状态：[ ]
- 范围：运行持久化、调度、公告、Dashboard、资源和玩家测试；检查全仓旧路径引用、生成目录和迁移映射完整性。
- 验证证据：
- 发现问题与修复：
- 剩余风险：
- 下一步：

## Task 7：实现 generation-first AssetResolver

- 状态：[ ]
- 范围：引入素材类型映射和 L1/L2/下载决策；接入当前 generation lease；先覆盖头像、立绘和武器图。
- 验收：L1 命中时零网络且不复制 L2；L1 缺失时命中 L2；双 miss 才下载；L1 损坏不被覆盖。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 8：改造共享自适应图片下载器

- 状态：[ ]
- 范围：长生命周期 AsyncClient、动态容量、AIMD 退避、Retry-After、URL 级 inflight、不同 target fan-out、原子写入和 lifecycle hook。
- 验收：同 URL 只产生一次真实请求；不同 URL 正常并发；失败和取消语义明确；stop/reload 无 client 或任务泄漏。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 9：并发准备角色详情素材并保持渲染契约

- 状态：[ ]
- 范围：在单一 generation lease 内并发技能、角色 Mod、武器、属性和立绘相关素材；按原业务顺序组装 payload。
- 验收：冷缓存不再逐项串行等待；无武器、特殊武器、多 Mod 和同 URL 多业务 ID 场景通过；占位和展示顺序不变。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Checkpoint 3：集中检查资源流水线

- 状态：[ ]
- 范围：运行 resolver、downloader、generation、player rendering 的完整相关测试；复查并发取消、lease 和 cache 原子性。
- 验证证据：
- 发现问题与修复：
- 剩余风险：
- 下一步：

## Task 10：编写手动迁移文档与发布说明

- 状态：[ ]
- 范围：更新 `docs/usage/resources.md` 和 `CHANGELOG.md`，记录停机备份、旧到新映射、可不迁移缓存、别名迁移和旧目录清理。
- 验收：文档不包含真实部署路径、凭据或固定测试数量；用户能按文档完成手动迁移和回滚。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 11：全量验证与交付审查

- 状态：[ ]
- 范围：运行相关测试、完整 pytest、ruff、compileall；检查 Git diff、旧路径残留、生成物和提交拆分。
- 验收：所有可归属失败已修复或明确记录；不存在未验证的验收条件；保留用户已有无关改动。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Checkpoint 4：最终集中检查与停止条件

- 状态：[ ]
- 范围：对全部任务、验收标准、测试证据和回滚说明做逐项审计；只有证据完整才允许标记 goal 完成。
- 验证证据：
- 未满足项：
- 下一步：
