# DNA 资源流水线与生产数据目录重构实施计划

日期：2026-09-09

## 1. 目标

本计划合并两项已经确认的改造：

1. 重构角色面板/卡片的素材解析与下载链路：同步资源优先、本地动态缓存次之、缺失素材走全局共享自适应高并发下载，并加入 URL 级 inflight 去重。
2. 重划分 `data/plugin_data/astrbot_plugin_dna/` 的生产目录，去除 `resource/`、`resource_generations/`、`other/`、顶层状态文件等历史混杂结构。

本次允许破坏性目录变更。当前没有确认到其他生产用户，因此不实现程序化兼容迁移；升级前由用户按文档手动迁移，新版本只认新结构。

## 2. 已确认决策

### 2.1 资源读取优先级

统一资源解析层按以下顺序取素材：

1. 当前已发布的 `dna-resource` generation，作为 L1 公共资源。
2. 运行时动态素材缓存，作为 L2。
3. 全局共享下载池联网获取缺失素材。
4. 下载成功后仅写 L2，不反向修改公共资源。

第一阶段公共资源映射至少覆盖：

- 角色头像：`images/role_avatar/<char_id>.png`
- 角色立绘：`images/role_paint/<char_id>.png`
- 武器图：`images/weapon/<weapon_id>.png`

Mod、技能图、属性图、武器属性图，以及公共仓库尚未收录的新素材继续按需下载。

### 2.2 公共资源 generation

保留现有 resource generation 原子切换模型。

- 同步期间继续使用上一代完整快照。
- 新 generation 校验完成后再原子切换。
- 资源解析器不得永久缓存一个旧 generation 根路径。
- 每次面板/卡片素材读取应通过 `ResourceSnapshotCoordinator` 或等价 lease 使用当前已发布 generation。

### 2.3 下载器

所有运行时图片下载共享同一个进程级下载组件：

- 一个长生命周期 `httpx.AsyncClient`。
- 复用 TCP/TLS/keep-alive 连接。
- 插件启动时初始化，停止/重载时显式关闭。
- 不再为每张图片创建独立 `AsyncClient`。
- 使用动态容量控制器，而不是创建后固定大小的 `asyncio.Semaphore`。
- 并发策略采用 AIMD 风格：健康时逐步增加，429/5xx/timeout/transport congestion 时快速降低。
- 429 优先遵守 `Retry-After`。
- 缩容只限制新任务进入，不取消已经开始的请求。
- 设置内部硬上限作为保险丝，首版建议 64；不暴露给用户配置。

### 2.4 URL 级请求去重

网络层 inflight key 改为完整 URL，而不是 `(URL, target_path)`。

同一 URL 同时被多个不同语义目标请求时：

1. 只产生一个真实 HTTP 请求。
2. 响应图片只校验一次。
3. 校验通过的 bytes 可以 fan-out 到多个目标缓存路径。
4. 目标文件仍保持各自业务 ID/文件名，不把不同 Mod 的业务语义合并。

不做 SHA-256 内容级去重。哈希去重发生在下载之后，无法解决重复网络请求，本次属于过度设计。

完整 URL 原样作为去重键，不擅自删除 query 参数。

### 2.5 渲染前并发准备

移除角色详情链路中可以独立执行的串行素材 I/O：

- 角色立绘/头像/元素属性图。
- 技能图。
- 角色 Mod 图。
- 多把武器的武器图。
- 各武器属性图。
- 各武器 Mod 图。

上层可以使用 `asyncio.gather` 积极提交独立任务，但实际网络并发由全局共享下载器统一限制，避免多用户请求形成并发乘法。

业务顺序和最终卡片展示顺序不得因并发准备改变。

## 3. 生产数据目录最终结构

目标结构：

```text
data/plugin_data/astrbot_plugin_dna/
├── db/
│   └── dna.sqlite3
│
├── state/
│   ├── subscriptions.json
│   ├── scheduler.json
│   ├── client_update.json
│   └── announcements/
│       ├── seen.json
│       └── delivery.json
│
├── resources/
│   ├── repository/
│   │   └── ... dna-resource Git 工作树
│   └── generations/
│       ├── current.json
│       ├── last_sync.json
│       ├── validation.json
│       └── <generation-sha>/
│
├── cache/
│   ├── assets/
│   │   ├── game/
│   │   │   ├── role_avatar/
│   │   │   ├── role_paint/
│   │   │   ├── weapon/
│   │   │   ├── skill/
│   │   │   ├── mod/
│   │   │   ├── attr/
│   │   │   └── weapon_attr/
│   │   └── user/
│   │       └── avatar/
│   │
│   ├── api/
│   │   ├── announcement/
│   │   ├── player/
│   │   └── mh/
│   │
│   ├── rendered/
│   │   ├── player/
│   │   └── notices/
│   │
│   └── media/
│       ├── announcement/
│       ├── sign/
│       └── calendar/
│
└── backups/
    ├── database/
    └── state/
```

目录语义：

- `db/`：核心持久数据库，不可作为缓存删除。
- `state/`：订阅、调度、公告投递等小型持久状态。
- `resources/`：公共资源仓库及原子 generation。
- `cache/`：理论上可全部删除并重新获取/生成的数据。
- `backups/`：人工或迁移前备份，不参与正常运行读取。

不再保留 `custom/`。自定义素材功能已移除，生产 `custom/custom_paint/` 为空且已经人工清理。

`rendered-pr42/` 是测试产物，不属于生产结构，已人工清理。

## 4. 旧目录到新目录的手动迁移表

新版本不执行自动迁移。发布说明和升级文档必须提供明确映射。

### 4.1 必须迁移的持久数据

| 旧位置 | 新位置 |
| --- | --- |
| `dnaby.sqlite3` | `db/dna.sqlite3` |
| `subscriptions.json` | `state/subscriptions.json` |
| `scheduler_state.json` | `state/scheduler.json` |
| `client_update_state.json` | `state/client_update.json` |
| `ann_state.json` | `state/announcements/seen.json` |
| `ann_delivery_state.json` | `state/announcements/delivery.json` |

历史数据库 `.bak*` 文件统一人工放入 `backups/database/`，不再散落在数据根目录。

### 4.2 公共资源

| 旧位置 | 新位置 |
| --- | --- |
| `resources/` Git 工作树 | `resources/repository/` |
| `resource_generations/` | `resources/generations/` |

注意 `resources/` 在新结构中成为资源域的父目录，因此旧结构检测不能仅判断顶层 `resources/` 是否存在，应检查 `resources/.git` 等旧形态标志。

### 4.3 动态素材缓存

| 旧位置 | 新位置 |
| --- | --- |
| `resource/mod/` | `cache/assets/game/mod/` |
| `resource/skill/` | `cache/assets/game/skill/` |
| `resource/weapon/` | `cache/assets/game/weapon/` |
| `resource/paint/` | `cache/assets/game/role_paint/` |
| 游戏角色 `resource/avatar/` | `cache/assets/game/role_avatar/` |
| 用户头像 `resource/avatar/` | `cache/assets/user/avatar/` |
| `resource/attr/` | `cache/assets/game/attr/` |
| `resource/weapon_attr/` | `cache/assets/game/weapon_attr/` |

`resource/avatar/` 目前混有游戏角色头像和平台用户头像，手动迁移时必须按业务 ID/现有调用来源拆分，不能整目录盲目移动到单一目标。

已经被 `dna-resource` 完整覆盖的公共素材可以不迁移 legacy 动态副本；首次读取应直接命中 L1 generation。

### 4.4 API/渲染/媒体缓存

| 旧位置 | 新位置 |
| --- | --- |
| `cache/player_data/` | `cache/api/player/` |
| `cache/player_card/` | `cache/rendered/player/` |
| `cache/announcement/` | `cache/api/announcement/` |
| `cache/mh/` | `cache/api/mh/` |
| 顶层 `rendered/` | `cache/rendered/`（按产物类型分流） |
| `other/ann_card/` | `cache/media/announcement/` |
| `other/sign/` | `cache/media/sign/` |
| `other/calendar/` | `cache/media/calendar/` |

这些都属于可重建数据，允许用户选择不迁移、直接清空冷启动。

### 4.5 明确废弃

以下旧结构不进入新模型：

- `custom/`、`custom/custom_paint/`。
- `rendered-pr42/`。
- 空的 `players/` legacy 目录。
- 已无业务调用且被公共资源替代的 legacy `resource/alias/`、`resource/id2name.json`，在最终实现前再次全仓搜索确认无依赖后删除。

## 5. Breaking Change 与 fail-fast

本次目录重构明确是破坏性改动。

### 5.1 不做兼容迁移

禁止加入：

- 自动 move/copy 旧目录。
- 启动时双读新旧目录。
- legacy fallback。
- 自动把旧数据库搬到新位置。
- 为兼容旧版本永久保留旧路径常量。

### 5.2 旧结构检测

若新版本启动时发现典型旧结构，应拒绝正常初始化并输出手动迁移提示，而不是悄悄创建一个全新空数据库继续运行。

至少检测：

- 顶层 `resource/`。
- 顶层 `resource_generations/`。
- 顶层 `other/`。
- 顶层 `rendered/`。
- 顶层 `dnaby.sqlite3`。
- 顶层旧状态 JSON。
- `resources/.git`（旧公共资源仓库形态）。
- legacy `cache/player_data`、`cache/player_card` 等旧 cache 子目录。

提示信息必须给出升级文档入口和至少核心数据库迁移路径。

当新目录结构已经完整，且不存在旧结构标志时正常启动。

## 6. AssetResolver 设计边界

新增统一素材解析组件，概念名 `AssetResolver`，最终命名遵循现有模块风格。

职责：

1. 根据素材类型与业务 ID 生成 L1/L2 候选路径。
2. 从当前 generation lease 中读取公共资源。
3. 校验本地图片。
4. L1 miss 后读取动态 cache。
5. L2 miss 后提交全局下载任务。
6. 下载完成后返回 cache 目标。

不负责：

- Git clone/pull。
- generation 构建和切换。
- HTML/PIL 布局。
- 卡片业务字段排序。
- 决定可选模块是隐藏还是显示占位。

公共 generation 始终只读；动态缓存可以安全替换损坏文件。

## 7. 缓存与失败语义

### 7.1 L1 公共资源损坏

- 记录安全日志。
- 不删除、不覆盖 generation 文件。
- 回退 L2。
- L2 也 miss 时允许网络获取到动态缓存。

### 7.2 L2 动态缓存损坏

- 复用已有图片完整性校验。
- 安全删除/替换损坏的普通缓存文件。
- 保持符号链接安全检查。

### 7.3 下载写入

- 写临时文件或内存 bytes。
- 完成图片校验。
- 通过 `os.replace` 等原子方式落盘。
- URL fan-out 时每个 target 都必须原子发布。
- 占位图不得持久化成真实素材缓存。

### 7.4 失败冷却

可对刚失败的相同 URL 设置短暂的进程内 cooldown，防止多人同时查询造成失败重试风暴。

不把失败永久缓存到磁盘。

## 8. 实施阶段

### Phase 1：统一运行期路径定义

1. 建立新的数据目录路径模块，集中定义 `db/state/resources/cache/backups`。
2. 删除/替换当前散落的 `MAIN_PATH / ...`、`runtime_database.path.parent / ...` 硬编码。
3. 删除已废弃 `CUSTOM_PATH/CUSTOM_PAINT_PATH` 与无调用方的原图缓存遗留逻辑，先做全仓引用确认。
4. 新增 legacy layout detector；发现旧结构时 fail-fast。
5. 不写任何自动迁移代码。

验收：空的新目录结构可以启动；旧结构直接给出明确错误。

### Phase 2：资源同步目录切换

1. `resource_repository_dir()` 改为 `resources/repository/`。
2. `resource_generations_dir()` 改为 `resources/generations/`。
3. 保持现有 manifest 校验、generation 创建、current 指针和原子发布行为。
4. 验证同步期间现有 generation 不受影响。
5. 不在本阶段优化 `.git` + generation 的磁盘重复问题。

验收：全新数据目录执行“同步资源”后可以生成并切换 generation。

### Phase 3：动态缓存目录切换

1. 将 legacy `resource/*` 调用迁到 `cache/assets/*`。
2. 角色头像与用户头像分域。
3. 去除 `resource/alias`、`id2name.json` 等确认无用的遗留路径。
4. 更新 weekly item 等资源：优先判定是否已经完全属于公共 generation；若已覆盖则不继续生成单独 legacy 动态副本。

验收：代码库中不再创建顶层 `resource/`。

### Phase 4：AssetResolver

1. 建立素材类型到 L1/L2 的映射。
2. 接入 generation lease。
3. 第一阶段完成角色头像、角色立绘、武器图的公共资源优先命中。
4. Mod/技能/属性等缺失素材保留按需下载。
5. 替换渲染器对 legacy `get_*_img` 的直接路径决策。

验收：同步仓库已有的头像/立绘/武器在 L2 全空时零网络命中。

### Phase 5：共享自适应下载器

1. 引入单个生命周期受控的 `AsyncClient`。
2. 引入可动态调整容量的全局调度器。
3. 实现 AIMD 增长/退避。
4. 保留 retry、429 `Retry-After`、5xx/timeout 处理。
5. 实现 URL 级 inflight 去重。
6. 实现一份响应向多个 target fan-out。
7. 保留原子写入与图片校验。
8. 插件停止/reload 时关闭 client，并处理待结束任务。

验收：相同完整 URL 即使 target 不同也只出现一个真实请求。

### Phase 6：渲染前并发准备

1. 技能图并发。
2. 角色 Mod 并发。
3. 多把武器并发。
4. 每把武器的 Mod 并发。
5. 立绘/属性图等无依赖素材并发。
6. 输出数据仍按原业务顺序组装。

验收：冷缓存角色详情不再按素材逐项串行等待。

### Phase 7：其余生产目录切换

1. 数据库迁到 `db/dna.sqlite3`。
2. 订阅/调度/公告状态迁到 `state/`。
3. API cache、成品 card、公告媒体/签到/日历进入新的 `cache/` 子域。
4. 数据库和状态备份统一进 `backups/`。
5. 删除代码中对顶层 `other/`、`rendered/`、旧状态文件位置的创建逻辑。

验收：全新运行后生产根目录只产生计划内的顶层目录。

### Phase 8：文档与发布

1. 在升级说明中标记 Breaking Change。
2. 提供手动迁移表和示例 shell 命令，但不让插件自动执行。
3. 明确哪些缓存可选择不迁移。
4. 提示先备份 `dnaby.sqlite3` 和状态文件。
5. 升级完成后要求旧目录全部移走，否则新版本拒绝启动。

## 9. 测试计划

### 9.1 路径与 Breaking Change

- 新目录首次启动创建正确。
- 旧 `resource/` 存在时 fail-fast。
- 旧根数据库存在时 fail-fast。
- `resources/.git` 旧仓库形态存在时 fail-fast。
- 新 `resources/repository/.git` 不误报。
- 不存在自动迁移副作用。

### 9.2 generation

- 同步过程中继续读旧 generation。
- 发布后新请求读取新 generation。
- 一个渲染周期内 lease 不跨 generation 混读。
- generation 中损坏资源安全回退 L2，不修改 L1。

### 9.3 下载器

- 同 URL / 同 target 单请求。
- 同 URL / 不同 target 仍单请求，并 fan-out 成多个目标文件。
- 不同 URL 正常并发。
- 429 正确读取 `Retry-After`。
- 5xx/timeout 触发并发退避。
- 健康窗口逐步升并发。
- 缩容不取消 active 请求。
- placeholder 不进入持久缓存。
- client lifecycle 可在 reload/stop 正确关闭。

### 9.4 渲染

至少使用真实或等价数据覆盖：

- 无特殊武器角色。
- 有特殊同律武器角色。
- 角色 Mod 较多。
- 武器 Mod 较多。
- 同一 URL 被多个不同 Mod ID 复用。
- 公共 L1 完整、L2 全空。
- 完全离线但 L1 公共资源存在。

## 10. 已有真实基准记录

这些数字用于证明方向有效，不作为 CI 的严格秒数断言，因为实时 CDN 延迟会波动。

### 10.1 松露

真实 Lv.80 数据，3 技能、9 个角色 Mod 槽、无武器 section。

- 当前冷动态缓存：`67.80s`
- 本地优先 + 高并发原型：`16.87s`
- 节省：`50.93s`
- 减少：`75.1%`
- 加速：`4.02x`
- T2I 约 `3s`，说明主要瓶颈是素材串行 I/O。

### 10.2 贝蕾妮卡 + 特殊同律武器伊弥尔

真实 Lv.80 / 6 命数据：3 技能、7 个已装备角色 Mod、特殊武器 3 个已装备武器 Mod，卡片约 `1000x2386`。

- 当前实现：`78.46s`
- 本地优先 + 高并发原型：`37.38s`
- 节省：`41.08s`
- 减少：`52.36%`
- 加速：`2.10x`

这一轮的 critical path 是单个约 `32.75s` 的慢素材，因此并发不能把总耗时降到该单请求以下。

### 10.3 URL 去重验证

伊弥尔三个不同 Mod ID/名称共用同一个 `Mod_Cerberus02.png` URL，返回字节完全一致。

使用一个长生命周期 AsyncClient + keep-alive 做重复 A/B：

- 三个相同 URL 并发请求：中位墙钟约 `0.434s`。
- URL 去重后一次请求：中位墙钟约 `0.240s`。
- 中位减少约 `44.6%`。
- 请求数 `3 -> 1`。
- 该图传输字节 `116,847B -> 38,949B`，减少 `66.7%`。
- 本轮尾部样本中，三请求组最坏约 `19.92s`，单请求组最坏约 `2.10s`。

URL 去重的主要价值是降低请求量、连接竞争和尾延迟；如果整批还有更慢的其他唯一 URL，则不保证整卡墙钟按同等比例继续下降。

## 11. 验收标准

1. 新版本只产生新的生产目录结构。
2. 旧结构存在时明确拒绝启动并提示手动迁移。
3. 无任何自动兼容迁移/双读 fallback。
4. 已同步公共头像/立绘/武器在动态 cache 空时不访问网络。
5. 缺失 Mod/技能等长尾素材通过共享高并发池获取。
6. 相同 URL 在同一 inflight 窗口内只发生一次真实 HTTP 请求，即使业务 target 不同。
7. 多用户同时请求不会按“用户数 × 每张卡几十连接”无限放大。
8. 429/5xx/timeout 下并发会自动退避，网络恢复后逐步回升。
9. 第二次请求同一角色时应接近纯数据读取 + T2I 渲染耗时。
10. 插件 reload/stop 后无泄漏 AsyncClient 或悬挂下载任务。
11. generation 同步/切换期间不出现半更新公共资源。
12. 数据库、订阅、调度和公告投递状态在手动迁移后完整保留。

## 12. 明确不做

本次不做：

- SHA-256 内容寻址去重。
- 同步后自动预热全部 Mod/技能素材。
- 用户可调的下载并发配置。
- 自动迁移旧生产目录。
- 长期 legacy fallback。
- 恢复已经移除的自定义素材功能。
- 把三个业务 Mod 因图标相同而合并为同一个 Mod。
- 顺手重构所有无关模块。
- 本阶段解决 `resources/repository/.git` 与 generation 完整快照造成的磁盘重复问题；该问题单独评估。

## 13. 推荐提交拆分

为降低 review 风险，建议按以下 tracer 顺序提交：

1. `refactor: define new runtime data layout and legacy guard`
2. `refactor: relocate resource repository and generation paths`
3. `refactor: relocate dynamic asset cache paths`
4. `feat: add unified asset resolver with generation-first lookup`
5. `feat: add shared adaptive image downloader`
6. `feat: deduplicate inflight image downloads by URL`
7. `perf: prefetch independent player card assets concurrently`
8. `refactor: relocate state api cache rendered media and backups`
9. `docs: document breaking manual data migration`
10. `test: cover resource resolution concurrency and data layout`

每一步都应保持测试可运行；目录路径切换和业务性能优化不要压成一个无法审查的大提交。
