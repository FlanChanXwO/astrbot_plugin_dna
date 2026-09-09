# Goal 1 计划：DNA 资源流水线与生产数据目录重构

## 目标

在隔离工作树中，为 `astrbot_plugin_dna` 初始化并执行一套可分轮推进的实施计划，最终完成：

- 生产数据目录切换到 `db/`、`state/`、`resources/`、`cache/`、`backups/`；数据库固定为 `db/dna.sqlite3`。
- 旧生产布局由人工迁移；新版本启动前检测旧结构并 fail-fast，不做自动迁移、双读或长期 legacy fallback。
- 保留现有 `ResourceSnapshotCoordinator` 的 generation 校验、原子发布和 lease 边界。
- 新增统一 `AssetResolver`：当前 generation 公共资源 L1，动态缓存 L2，缺失时按需联网下载。
- 先接入 `dna-resource` 已有的角色头像、角色立绘和武器图；不扩充资源仓库。
- 所有运行期图片下载共享长生命周期 `httpx.AsyncClient`、动态并发控制和完整 URL inflight 去重。
- 渲染前并发准备独立素材，同时保持业务顺序、占位和错误语义。

## 已确认约束

- 公共资源只需与本地缓存二选一；按具体素材判断是否存在，不按目录整体判断。
- 公共资源命中时不复制到动态缓存；同步后新请求自动使用新 generation，旧动态副本不自动清理。
- 缺失素材由插件按需自动下载；下载成功只写动态缓存。
- 下载失败保留现有占位和脱敏日志语义，占位图不得写入持久缓存。
- stop/reload 时拒绝新下载，等待已经开始的请求自然完成，再关闭共享 client；不取消 active HTTP 请求。
- 自定义角色/武器别名仍有业务消费者，迁入 `state/aliases/char.json` 和 `state/aliases/weapon.json`。
- 不做 SHA-256 内容级网络去重、全量预热、用户可调并发、自动迁移或无关重构。
- 每个 task 必须遵循 Red → Green → Refactor，并提交独立、可审查的变更。

## 当前事实与风险

- 当前数据库仍由 `AsyncDatabase.from_data_dir()` 定位为数据根下的 `dnaby.sqlite3`，大量 bootstrap 路径通过 `database.path.parent` 推导。
- 当前旧 `RESOURCE_PATH` 存在导入期 `mkdir`，可能在 legacy detector 执行前创建旧目录；必须先清除该副作用。
- 当前图片下载器按 `(URL, target)` 合并且每次下载创建 client；需要改为 URL 级共享任务和生命周期注入。
- 当前 generation coordinator 已有 `bind_resource` / `bind_renderer` lease API，应优先复用而非重写。
- 当前 typed cache 尚未自然映射到 `cache/api`、`cache/rendered`、`cache/media`，需要逐个替换 bootstrap 和业务注入路径并保持测试夹具独立。
- 客户端更新状态已有旁车备份语义，迁移到 `backups/state/` 时要保持可恢复性。

## 实施策略

1. 先建立统一运行期路径和 legacy guard，避免后续代码继续产生旧结构。
2. 切换数据库、状态、资源仓库、generation、缓存、渲染和媒体路径。
3. 复用 generation lease，接入 L1/L2 AssetResolver。
4. 改造共享图片下载器、动态容量和 URL fan-out。
5. 在同一 lease 内并发准备玩家卡素材，保留渲染结果顺序。
6. 补齐手动迁移文档、CHANGELOG 和跨模块验收。

## 验证与回滚

- 最小验证顺序：目标回归测试 → 相关领域测试 → `ruff check .` → `python3 -m compileall .` → 必要时完整 `python3 -m pytest`。
- 每次目录路径改动都验证新目录创建、旧布局拒绝、无自动搬迁副作用。
- 每次资源链路改动都验证 L1/L2 优先级、generation 一致性、图片完整性和网络请求数量。
- 生产升级前由部署者完整备份旧数据目录；失败时停止新版本、恢复备份并回到旧插件版本。代码不实现自动回滚。

## 交付边界

本 goal 初始化只创建 `goal-1/` 工作文件并准备隔离工作树；后续每轮只执行 `tasks.md` 的第一个未完成 task。不得在单轮合并多个 task，也不得在未有测试证据时宣称完成。

## 假设

- 当前项目使用 Python/pytest/ruff，仓库根目录的 `AGENTS.md` 为长期规则来源。
- `dna-resource` 的现有公共图片目录契约保持不变。
- 新布局是 breaking change，发布说明必须明确人工迁移和旧目录清理要求。
