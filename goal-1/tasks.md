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

- 状态：[ ]
- 范围：检测旧数据库、旧 resource/generation、旧状态、旧 rendered/other、旧 cache 和 `resources/.git` 旧形态；确保检测早于任何新目录或数据库写入。
- 验收：旧结构明确失败并包含迁移提示；新结构通过；无自动复制、移动或双读。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 3：消除旧路径导入期副作用并切换数据库路径

- 状态：[ ]
- 范围：移除旧 `RESOURCE_PATH`/`name_convert` 导入期创建副作用；数据库改为 `db/dna.sqlite3`；保留别名业务能力但改由 layout 提供路径。
- 验收：导入模块不创建旧目录；数据库初始化只写新路径；别名调用方仍可工作。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Checkpoint 1：集中检查路径切换

- 状态：[ ]
- 范围：复查 Task 1-3 的 diff、引用和启动顺序；运行路径、持久化和别名相关测试。
- 验证证据：
- 发现问题与修复：
- 剩余风险：
- 下一步：

## Task 4：切换公共资源 repository 与 generation 路径

- 状态：[ ]
- 范围：将资源工作树切到 `resources/repository/`，generation 切到 `resources/generations/`，保留 manifest 校验、原子发布和 lease。
- 验收：全新数据目录同步并发布 generation；同步期间旧 generation 可读；新 repository `.git` 不触发 legacy guard。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 5：切换动态素材、API、渲染和媒体缓存路径

- 状态：[ ]
- 范围：迁移 `resource/*` 到 `cache/assets/*`，拆分游戏头像和用户头像，迁移 API、玩家卡、MH、顶层 rendered 和 other 媒体路径。
- 验收：新运行不会创建顶层 `resource/`、`rendered/` 或 `other/`；缓存读写和清理语义保持不变。
- 实际变更：
- 验证证据：
- 剩余风险：
- 下一步：

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
