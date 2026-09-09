# Goal 5 Tasks：插件资源瘦身与外置

> 每轮只执行第一个未完成项；普通代码 task 必须按 TDD Red → Green → Refactor；每三个普通 task 后执行一次集中检查-debug。每个 task 单独提交，只暂存本 task 所有文件。初始化前已有修改、其他 goal 文件和私有资源不得混入提交。

## Task 01 — 资源现状、依赖路径与真实包体积基线 `[completed]`

**目标**：建立可复核的资源清单、重复字体清单、renderer/旧 utils 路径消费者清单和真实发布包体积基线，不修改业务代码。

**范围**：`src/resources/`、`src/utils/`、`src/infrastructure/resources/`、`src/infrastructure/rendering/`、相关测试/README/打包规则；必要时使用现有打包脚本。

**验收**：记录所有大于 100 KiB 的候选文件、重复字体的哈希/路径、直接路径消费者、现有 manifest/generation/lease/listener seam；记录真实打包方式、字节数和 MiB；说明 `tests/.data`/Python/ruff 等环境阻塞。

- 实际做了什么：
  - 在隔离 worktree `codex/resource-slimming-design`、提交 `d748fe1` 的干净基线 (`HEAD=0327a0a` 后初始化提交) 上只做只读盘点，没有修改业务代码。
  - 统计 `git ls-files`：全仓 819 个 tracked files；`src/resources/` 与 `src/utils/fonts/` 共 339 个资源文件、172,537,145 bytes（164.544244 MiB）。其中 `src/resources/` 为 331 个文件、115,990,863 bytes（110.617507 MiB），`src/utils/fonts/` 为 8 个文件、56,546,282 bytes（53.926737 MiB）；纹理 273 个文件、58,801,938 bytes（56.077898 MiB），字体 8 个文件、56,546,282 bytes（53.926737 MiB），帮助素材 48 个文件、640,131 bytes（0.610476 MiB）。
  - SHA-256 盘点发现 11 个重复 digest 组、可去除的重复副本合计 56,593,269 bytes。7 组是完整字体的 `src/resources/fonts/` 与 `src/utils/fonts/` 双份：`arial-unicode-ms-bold.ttf` 17,942,992 bytes、`MiSansVF.woff2` 11,867,816 bytes、`NotoColorEmoji.ttf` 10,195,752 bytes、`arial-unicode-ms-bold-fallback.woff2` 5,774,400 bytes、`dna_fonts.ttf` 5,632,220 bytes、`dna_fonts.woff2` 2,805,896 bytes、`arial-unicode-ms-bold.woff2` 2,324,528 bytes；其余重复项为 `common/div.png` 与 `stamina/div.png`、两组帮助图标，以及两个相同的 `dna_fonts.py`。
  - 大于 100 KiB 的首批候选由字体占据前 14 个大文件：最大为双份 `arial-unicode-ms-bold.ttf`（每份 17.111771 MiB）、双份 `MiSansVF.woff2`（每份 11.318031 MiB）、双份 `NotoColorEmoji.ttf`（每份 9.723427 MiB）、双份 fallback WOFF2（每份 5.506897 MiB）、双份 `dna_fonts.ttf`（每份 5.371304 MiB）、双份 `dna_fonts.woff2`（每份 2.675911 MiB）、双份 Unicode WOFF2（每份 2.216843 MiB）；最大非字体纹理为 `src/resources/textures/stamina/bg/bg6.png`，2,463,458 bytes（2.349337 MiB），随后是角色/攻略/日历/签到背景和 frame。
  - 直接路径消费者已定位：`src/infrastructure/rendering/fonts.py:9` 的 `BUNDLED_FONT_PATH` 与 `load_runtime_font()` fallback；`player.py:62-66` 的 common/detail/role/font 常量及其多处模板 payload；`encyclopedia.py:55-61` 的 common/stamina/weekly/calendar/font 常量；`checkin.py:30-34` 的 common/sign/font 常量；`notices.py:58-63` 的 common/mh/ann/font/unicode 常量；`help.py:20` 的 `MiSansVF.woff2` 及 common/help 纹理；`payloads.py:15` 的 common 纹理；`src/utils/image.py:26,70` 的 legacy `texture2d` 路径；`src/utils/fonts/dna_fonts.py`、`src/resources/fonts/dna_fonts.py` 的三类字体路径；`src/utils/resource/RESOURCE_PATH.py` 与 `src/resources/resource/RESOURCE_PATH.py` 的运行期资源路径；`src/infrastructure/resources/encyclopedia.py:257-258` 的 snapshot 字体路径。`dnaby/` 目录在当前 worktree 不存在，不能把它当作实际消费者。
  - 现有资源 seam 已核实：`ResourceGenerationValidator` 在 `src/infrastructure/resources/generation.py:313`，`ResourceSnapshotCoordinator` 在 `generation.py:414`，listener 注册为 `subscribe()`（约 463 行），空/可选快照入口为 `optional_lease()`（约 563 行）；`ResourceManifest.validate_runtime_layout()` 在 `src/infrastructure/resources/manifest.py:131`；`EncyclopediaResourceStore`/`from_root()` 在 `src/infrastructure/resources/encyclopedia.py:110/165`；`ResourceMap`/`from_root()` 在 `src/infrastructure/rendering/player.py:548/559`。这些是后续统一解析边界应复用的既有 contract，不新建第二套下载或 snapshot 管理。
  - 没有发现仓库专用的市场打包脚本。按当前 tracked HEAD 执行 `git archive --format=zip HEAD` 得到可复现的 source-archive baseline：917 entries，压缩包 155,708,550 bytes（148.495245 MiB），ZIP 成员压缩总和 155,555,598 bytes（148.349379 MiB），未压缩总量 177,794,502 bytes（169.558050 MiB）。其中 `src/` 压缩后 154,622,977 bytes（147.459962 MiB），所以这是包含测试/文档/goal 记录的保守上界，不把它误报成市场后端的隐式排除规则；后续仍以真实提交 zip 复测。官方 AstrBot 发布文档 URL 已记录在计划来源中，确认市场以 zip 作为体积门槛。
- 验证证据：
  - 只读命令：`git ls-files` + Python SHA-256/字节统计、`git archive --format=zip HEAD` + Python `zipfile` 统计、`rg` 路径消费者检索、LSP 的符号定位/引用扫描。
  - `tests/.data` 在当前隔离 worktree 缺失；初始化基线 `python3 -m pytest` 在 `conftest.py` 收集阶段因 `tests/.data` 不存在退出码 4（`FileNotFoundError`），不是本 task 引入的回归。系统 Python 为 3.14.4，`pytest`/Pillow/SQLAlchemy/SQLModel 可导入，但 `ruff` 模块缺失；后续按仓库约定优先使用项目 `.venv` 或 runtime 根目录命令。
  - 盘点生成的完整原始报告保存在本轮临时证据 `/tmp/dnaby-goal5-task01-current/resource-inventory.txt` 与 `/tmp/dnaby-goal5-task01-current/package-baseline.txt`；它们未写入仓库，避免把构建产物或大资源加入提交。
- 剩余风险：
  - `git archive` 只是当前仓库可复现的保守 baseline，市场服务是否排除 `tests/`、`docs/` 或 goal 记录尚未由本地发布工具确认；最终必须按实际提交路径重新构建并测量。
  - 资源仓库 `dna-resource` 不在本机工作区；字体/纹理的最终归属、manifest 哈希和跨仓库可验证 generation 由 Task 02 审计，当前不能安全删除任何大文件。
  - 目前大量 renderer 仍直接拼接插件目录路径，字体 fallback 仍会把缺失资源转成 `FileNotFoundError`；这正是后续 Red/Green 任务的范围。
- 下一步建议：Task 02 审计 `dna-resource` 可访问性、manifest `file_hashes`/`resource_version` 和现有 generation validator；在没有跨仓库证据前不删除资源。

## Task 02 — `dna-resource` 仓库与 manifest 能力审计 `[completed]`

**目标**：确认完整字体/纹理应该落在哪个资源仓库、现有 manifest 结构和 validator 能力，列出必须补齐的文件与哈希；若仓库不可访问，形成明确阻塞记录。

**范围**：可访问的本地/远程 `dna-resource` 仓库、`src/infrastructure/resources/manifest.py`、generation validator、资源文档；不伪造远端变更。

**验收**：得到资源仓库路径/分支/版本、目标文件列表、`resource_version` 更新点、`file_hashes` 约束和验证命令；未授权或不可访问时只记录事实并标记阻塞，不把假设当完成。

- 实际做了什么：
  - 通过插件现有配置确认资源仓库为 `https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git`，公开 `main` 可访问；审计用浅克隆位于 `/tmp/dna-resource-audit-goal5`，工作树干净。
  - 当前资源版本固定事实为 commit `5b1c4600d9be71480690811d4439ff8ffb65264a`（`2026-09-03T02:07:59+08:00`，`docs: describe panel/ as generic card backgrounds`）。资源仓库 README 明确要求先在 `main` 合并并记录 commit SHA/`resource_version`，再跑插件 generation validator，最后由插件只取 `main`；错误发布用普通 revert，不 force-push。
  - 当前 `resource_manifest.json` 为 `format_version=1`，`resource_version=redeem-code-v1-migration-2026-08-28`，声明 `fonts`、`images`、`panel`、`alias`、`data`、`schemas`、`wiki/role`、`wiki/weapon`、`wiki/spirit`、`guide`、`weekly_item`、`calendar`；`calendar/` 目前只有占位文件，尚无真实日历素材。
  - 资源仓库当前 327 个 tracked files、142,369,614 bytes（约 135.774 MiB）；已有 `role_avatar`、`role_paint`、`weapon`、`panel`、`wiki`、`guide`、`weekly_item` 等资源目录。当前本地仍有 `textures/calendar`、`common`、`detail`、`role`、`stamina`、`weekly_report` 等分类，不能在本 task 中假设它们已被外部仓库接管。
  - 字体目标清单与现状：已存在 `fonts/dna_fonts.ttf`、`fonts/arial-unicode-ms-bold.ttf`、`fonts/NotoColorEmoji.ttf`；仍缺 `fonts/dna_fonts.woff2`、`fonts/arial-unicode-ms-bold.woff2`、`fonts/arial-unicode-ms-bold-fallback.woff2`、`fonts/MiSansVF.woff2`。规格要求外置的角色/武器/面板、guide/wiki、字体与大型卡片/日历/背景纹理，后续必须以真实资源提交逐项补齐，不能由插件本地路径或未验证 candidate 代替。
  - `ResourceManifest` 的 `file_hashes` 是可选的相对路径到 SHA-256 映射；路径禁止绝对路径、反斜杠、`.`/`..`，摘要必须匹配 64 位十六进制 SHA-256。当前 manifest 未声明 `file_hashes`（解析后数量为 0），后续补入大字体/关键纹理时应在同一 manifest 中记录并由 generation validator 校验。`resource_version` 的唯一更新点是资源仓库根目录的 `resource_manifest.json`，插件 snapshot 同时保存该值。
- 验证证据：
  - `git ls-remote --heads --tags https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git` 成功返回 `main` 的 `5b1c4600d9be71480690811d4439ff8ffb65264a`；未发现需要伪造的本地资源仓库变更。
  - 使用项目 venv 执行 `PYTHONPATH=. /Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python`，加载 `ResourceManifest` 并执行 `ResourceManifest.load(root / "resource_manifest.json").validate_runtime_layout(root)`：`manifest_runtime_layout=PASS`。
  - 对同一克隆执行 `ResourceGenerationValidator().validate(root, "5b1c4600d9be71480690811d4439ff8ffb65264a")`：`generation_validation=PASS`；snapshot 的 `resource_version=redeem-code-v1-migration-2026-08-28`，`content_sha256=ab4fd52ff78fe133e81d278875c936e79a7423d13a4de78ac40131c2c2fd8dfc`，player/encyclopedia 的字体解析均指向 snapshot 下的 `fonts/dna_fonts.ttf`。
- 剩余风险：资源仓库当前 HEAD（2026 年 9 月 3 日）尚未包含规格要求的全部字体变体和本地大型卡片/日历/背景纹理；manifest 尚未声明关键文件哈希；本 task 只做审计，没有向公共仓库写入或发布任何资源。
- 下一步建议：执行 Task 03，冻结 verified snapshot/bootstrap/placeholder 的解析边界和 `incomplete` 语义；在此之前不删除插件内字体或大型纹理。

## Task 03 — 统一解析边界与 fallback 契约集中检查 `[completed]`

**类型**：集中检查-debug（Task 01–02 后提前检查；此处冻结设计，避免在缺少资源仓库证据时删除文件）。

**检查**：核对规格目标/非目标、当前 `ResourceSnapshotCoordinator` 的真实语义、空 snapshot 行为、renderer 消费点、资源仓库依赖和可回滚点；确定 `RuntimeAssetResolver` 是新增边界还是扩展现有 `ResourceMap`/`EncyclopediaResourceStore`，并写出逻辑 key/来源/incomplete 规则。

- 实际检查：
  - 规格目标冻结为：完整字体、大型纹理、角色/武器/面板等静态资源只从已验证 snapshot 提供；插件未同步时仍能启动，视觉命令走 bootstrap/placeholder/简化渲染；不新增自动同步、不把缺资源变成普通命令拒绝、不读取未验证 candidate 或 Git cache。失败同步继续保留旧 snapshot，资源版本刷新只影响新请求。
  - 已核对 `ResourceSnapshotCoordinator` 的真实语义：`ResourceSnapshot` 只由 `ResourceGenerationValidator` 校验后构造（`src/infrastructure/resources/generation.py:42-58,313-367`）；无 `current.json` 时 `initialize()` 返回 `None`（`generation.py:527-550`），严格 `acquire()` 抛 `ResourceGenerationError`（`552-560`），`optional_lease()`/`bind_resource()` 返回 `None`（`562-586`），`bind_renderer()` 在空 snapshot 时原样返回 renderer（`588-598`）。有 snapshot 时 lease 固定当前 generation，旧目录等待最后一个 lease 释放后回收；因此 resolver 必须是请求期视图，不能把 `Path`/resolver 长期缓存到下一次 generation。
  - 冻结架构决策：新增一个**薄的、只读、请求期** `RuntimeAssetResolver` 边界，但不新增 downloader、Git/cache、第二套 generation 或资源存储。它组合/适配现有 `ResourceMap` 与 `EncyclopediaResourceStore`（后两者继续作为 snapshot 内的领域索引和兼容 API），由 coordinator 的 lease/bind seam 提供；verified snapshot 内可增加 resolver 视图字段，bootstrap 则使用独立的显式 allowlist resolver。renderer 只消费逻辑 key/解析结果，不再拼接资源物理目录。
  - 冻结逐 key 来源优先级：
    1. `verified_snapshot`：仅读取当前 `ResourceSnapshot.root` 及其已校验索引；路径必须是 generation 内普通文件，不能回退到 `repository`、`.candidate-*`、Git checkout/cache 或网络下载。
    2. `bootstrap`：仅读取代码包中登记的固定 allowlist；allowlist 是逐逻辑 key 的显式映射，不是递归读取整个 `src/resources`。当前 `bootstrap.py:242-265` 在无 snapshot 时把 `resource_cache_root` 当作 `resource_root`，这是待 Task 05 修正的已确认越界路径。
    3. `placeholder` 或 `None`：缺失视觉素材时在内存生成简化结果，或对严格素材返回 `None`/既有用户可见“未找到”语义；resolver 不下载、不写入缓存、不伪造成功。
  - 冻结逻辑 key（key 不暴露绝对路径；资源仓库物理目录由映射表决定）：
    | 类别 | 最小 key 形态 | verified snapshot 典型路径 | 缺失处理 |
    | --- | --- | --- | --- |
    | 字体 | `font:dna_fonts`、`font:unicode_bold`、`font:emoji` | `fonts/<filename>` | bootstrap 字体若被明确保留则可用，否则字体 fallback/简化渲染并标记降级 |
    | 角色/武器 | `image:role_avatar:<id>`、`image:role_paint:<id>`、`image:weapon:<id>` | `images/role_avatar`、`images/role_paint`、`images/weapon` | 卡片内存占位或删去可选图片；不触发网络下载 |
    | 面板 | `panel:original:<char_id>` | `panel/<char_id>.png` | 简化面板/占位；详情仍遵循已有严格失败语义边界 |
    | 公共纹理 | `texture:<family>:<name>`（`common`、`detail`、`role`、`calendar`、`stamina`、`weekly_report`、`ann`、`sign`、`help` 等） | 由 manifest/资源映射表决定，不能由调用方拼接插件路径 | 允许简化渲染或 placeholder；纹理缺失不使插件启动失败 |
    | 资料素材 | `wiki:<kind>:<name>`、`guide:<name>:<provider>`、`weekly_item:<id>`、`calendar:<basename>` | `wiki/*`、`guide/*`、`weekly_item/*`、`calendar/*` | wiki/guide 等严格图片命令返回既有 not-found；周报/日历卡片可降级并记录来源 |
  - 冻结解析结果元数据：`source` 只允许 `verified_snapshot`、`bootstrap`、`placeholder`、`none`；对应 `status` 分别为 `provided`、`fallback`、`placeholder`、`missing`。外置 key 只要实际来源不是 `verified_snapshot`（bootstrap、placeholder、none）就属于本次视觉降级，渲染结果必须聚合为 `incomplete=True`，且不得覆盖完整卡片缓存；保留在插件中的 bootstrap-only logo/help 小资源不因正常使用自动标记不完整。metadata 的 `source` 使用稳定逻辑相对路径/来源标签，不暴露绝对路径。
  - 冻结生命周期与错误边界：resolver 只在 `bind_renderer`/等价 resolver context 内读取，新的 snapshot 只影响新请求；需要在 lease 结束后继续发送的 snapshot 素材先复制到受控 `rendered/`。缺失文件只走明确的 placeholder/`None` 分支；manifest、generation、transport、调用方和 I/O 的非预期异常继续显式暴露，不用 broad catch 或“默认成功”吞掉。严格公告详情等既有完整链路不得改成占位图。
  - 已确认的 renderer 消费缺口：`PlayerRenderer._item_payload()` 仍直接调用 legacy `get_avatar_img/get_weapon_img`（`player.py:85-109`）；百科周报的 metadata 读取 `weekly_assets`，但 `render_weekly_report()` 没把它传给 `_draw_weekly_report_card()`（`encyclopedia.py:237-267,891-984`），实际路径会继续走 legacy cache/网络/placeholder；日历 `_event_image()` 仍访问 legacy `CALENDAR_PATH`/网络（`encyclopedia.py:530-537`）；百科、公告、签到仍直接使用 bundled `FONT_ORIGIN_PATH`。`RenderedEncyclopediaImage` 目前也没有 `incomplete` 字段（`encyclopedia.py:686-696`），后续 renderer Red/Green 必须补齐“实际 bytes 来源”和缓存语义，而不能只改 metadata。
  - listener/刷新边界：现有 `subscribe()` 不回放当前 snapshot；`_activate()` 在 coordinator lock 内同步调用 listener，listener 异常可能阻断 retired cleanup。此次不另起 listener 机制；Task 06/后续回归要验证异常、重入、重复订阅和刷新期间的 lease 行为，resolver 不得绕过 coordinator。
- 验证证据：
  - 使用 Python LSP 对 `ResourceSnapshotCoordinator`、`ResourceMap`、`EncyclopediaResourceStore`、`PlayerRenderer`、`EncyclopediaRenderer` 与四个 service 的符号/引用做语义检查；关键定义与调用点见上列 `file:line`，确认当前没有现成 `RuntimeAssetResolver`。
  - 静态检索确认 legacy 资源入口仍存在：`src/infrastructure/rendering/{player,encyclopedia,checkin,notices}.py` 的 `RESOURCES_DIR`/`FONT_ORIGIN_PATH`，`src/utils/image.py` 的网络/legacy cache loader，以及 bootstrap 无 snapshot 读取 `resource_cache_root`；这为 Task 04/07 的 Red 契约提供真实失败点。
  - 测试覆盖审计确认 generation 正常发布、失败保留旧 snapshot、lease pinning、manifest/path 校验已有覆盖；空 snapshot 四种 context API、listener 异常、最终渲染 bytes 来源、统一 fallback/incomplete 尚无完整契约测试。Task 03 只做集中审计，未伪造测试通过。
- 新增修复 task：无；已将空 snapshot/resolver 优先级纳入 Task 04–05，将最终 renderer bytes/incomplete 纳入 Task 07–08，将 listener/lease 并发与异常纳入 Task 06/09。
- 剩余风险：当前 bootstrap 仍可能把未验证 Git cache 当资源视图；主要 renderer 仍混用 generation metadata 与 legacy path/network；周报 metadata 与最终 bytes、日历 metadata 与实际 lookup 可能不一致；listener 异常清理和 encyclopedia 的 `incomplete` 传递尚未实现。上述风险均有后续 task 承接，故本检查完成但不代表资源已迁移。

## Task 04 — 统一资源解析与降级路径 Red 契约 `[completed]`

**目标**：测试先行固定 verified snapshot → bootstrap allowlist → placeholder/`None` 的优先级、逻辑 key、不可读取 candidate 和缺失资源的 `incomplete` 语义。

**范围**：`tests/` 资源/generation/renderer 相关测试与最小 fake；只新增/扩展测试，不写生产实现。

**验收**：实际运行目标测试并确认因缺少/不完整解析 seam 失败；覆盖字体、纹理、角色/武器/panel 至少各一类、空 snapshot、bootstrap 命中、文件缺失、candidate 未验证、来源元数据和 `incomplete`。

- 实际做了什么：
  - 新增 `tests/test_goal5_asset_resolver.py`，只定义公共行为契约，没有修改生产代码。
  - 覆盖已验证 snapshot 优先于 bootstrap（`font.primary_ttf`、`texture.common.card`）、角色头像/立绘、武器和 panel 逻辑 key；断言 `source=verified_snapshot`、`status=provided`、`incomplete=False` 及实际路径。
  - 覆盖无 snapshot 时仅命中显式 bootstrap allowlist；未列入 allowlist 的 legacy cache 不得被递归读取，bootstrap 资源标记 `source=bootstrap/status=fallback`。
  - 覆盖 snapshot 文件缺失时回退 bootstrap、明确创建的 `.candidate-unverified` 与 `resources-cache` 不被读取；覆盖完全缺失资源返回 `source=none/status=missing/incomplete=True`，供 renderer 进入 placeholder/简化渲染。
  - 覆盖现有空 snapshot coordinator 契约：`initialize() is None`、`acquire()` 抛错、`optional_lease()`/`bind_resource()` 返回 `None`、`bind_renderer()` 原样返回 renderer。
- 验证证据：
  - Red 阶段实际执行：`PYTHONPATH=. /Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest --confcutdir=tests tests/test_goal5_asset_resolver.py -q`。
  - 结果为收集失败（退出码 2）：`ModuleNotFoundError: No module named 'src.infrastructure.resources.resolver'`，失败原因正是当前尚未实现统一 resolver seam；未把失败伪装成跳过或成功。
  - `ruff check tests/test_goal5_asset_resolver.py`、`git diff --check` 通过；Python LSP 对新增测试文件无诊断。提交：`ccb0ccc test(goal-5): define asset resolver red contract`。
- 剩余风险：当前测试在 import 阶段即失败，因此空 snapshot 的新增断言尚未实际执行；placeholder 的最终图片 bytes、renderer 缓存禁止覆盖、真实 snapshot lease/listener 刷新仍需 Task 05/06/07 覆盖。测试构造使用显式 logical-to-relative 映射，Task 05 必须保持路径安全并接入真实 `ResourceSnapshot`，不能只实现测试专用 fake。
- 下一步建议：执行 Task 05，实现最小 `RuntimeAssetResolver` 并接入现有 verified snapshot、bootstrap allowlist、空资源视图和 listener 刷新，使本 task 转 Green。

## Task 05 — 统一资源解析 Green 与现有 snapshot 接入 `[completed]`

**目标**：实现最小统一资源解析边界，接入现有 verified snapshot、bootstrap allowlist、空资源视图和 listener 刷新，不新增下载器或第二套 cache。

**范围**：`src/infrastructure/resources/`、必要的 `src/infrastructure/rendering/` seam、最小公共类型；不删除大资源。

**验收**：Task 04 Red 转 Green；renderer 不需要知道资源物理目录；只读 verified snapshot；candidate/Git cache 不可直接消费；空 snapshot 能返回明确降级状态；snapshot 发布后新的请求拿到新视图。

- 实际做了什么：
  - 新增 `ResolvedAsset` 与 `RuntimeAssetResolver`，固定 verified snapshot → 显式 bootstrap allowlist → `none/missing/incomplete` 优先级；snapshot 路径只接受 generation 内 POSIX 相对路径，拒绝绝对路径、`..`、反斜杠、符号链接和越界文件，不扫描 candidate/Git cache。
  - 在 `ResourceSnapshotCoordinator` 增加 `bind_resolver()`，复用现有 `optional_lease()`，使解析器按请求绑定当前 generation；从资源包稳定导出公共类型。
  - bootstrap 拆开 `resource_repository_root` 与 verified `resource_root`；无 verified snapshot 时使用空 `ResourceMap`/`EncyclopediaResourceStore`，不再从 repository cache 构造业务资源视图；保留资源更新服务对 repository root 的维护边界。
  - 注册 `bind_resource_resolver` request seam，登记字体 snapshot logical key 和小型数字纹理 bootstrap allowlist；保留现有 listener 刷新 legacy 资源视图，并在 generation 发布后刷新别名默认路径。
  - 将既有完整资源 bootstrap 测试改为显式 verified snapshot fixture，并补充无 snapshot、bootstrap 命中和 resolver binding 契约测试。
  - 实现提交：`0b43a47 feat(goal-5): add runtime asset resolver`。

- 验证证据：
  - Red：新增 binding/空资源视图测试后，目标测试先因缺少 `src.infrastructure.resources.resolver` 收集失败；实现后 `PYTHONPATH=. .venv/bin/python -m pytest --confcutdir=tests tests/test_goal5_asset_resolver.py tests/test_config_resources.py::test_bootstrap_injects_complete_runtime_resource_root -q` 通过，9 passed。
  - 资源/generation/config/operations 相关回归：42 passed；另有 `tests/test_entry_skeleton.py::test_plugin_can_initialize_and_terminate_with_admin_web_registrations` 因本机 `127.0.0.1:6189` 已被占用失败，属于环境端口冲突，非本次变更断言失败。
  - 变更文件 Python LSP diagnostics 均为空；目标文件 `ruff check`、`compileall`、`git diff --check` 通过。提交 hook 的 ruff check 也通过；全仓手动 ruff 仍报告既有 scripts/其他测试文件问题，未扩大范围修复。

- 剩余风险：
  - 主要 renderer 尚未消费 logical key/resolver，仍由 Task 07-09 迁移；当前 `bind_resource_resolver` 是公共 request seam，尚未替换 legacy 图片/字体读取。
  - bootstrap 只登记了现有小型数字纹理；完整字体和角色/武器/面板等映射等待资源仓库补齐与 renderer 迁移。`font.help` 的完整 bootstrap 语义保留在 resolver contract 中，但当前插件未登记字体子集路径。
  - `_activate()` listener 异常与 lease 并发清理仍按计划留给 Task 06/09；旧百科资源对象在 legacy listener 路径中的 generation 生命周期需后续集中复查。

- 下一步建议：执行 Task 06，集中检查 resolver 深度、路径安全、`incomplete` 状态、lease 与 listener 并发边界。

## Task 06 — 解析边界集中检查 `[completed]`

**类型**：集中检查-debug（Task 04–05）。

**检查**：复查 resolver API 深度、来源优先级、路径安全、None/placeholder/incomplete 语义、快照租约和 listener 并发边界；运行资源/generation/现有 renderer 回归，发现问题就在 tasks.md 末尾追加修复 task。

- 实际检查：
  - 复查 `RuntimeAssetResolver.resolve()` 与 `ResourceSnapshotCoordinator.bind_resolver()`：解析器只有一个只读 `resolve(logical_key)` seam，请求级 binding 复用现有 generation `optional_lease()`；实现没有扫描目录、读取 Git cache/candidate、下载或网络副作用。
  - 核对来源优先级为 verified snapshot → 显式 bootstrap allowlist → `none/missing/incomplete`；无 snapshot 时 bootstrap 数字纹理仍可用，未同步的完整资源不会被误认为已提供。`placeholder` source/status 由后续 renderer 的程序化降级负责，当前 resolver 的 `none/missing` 是明确的占位入口。
  - 补充路径安全回归：拒绝绝对路径、`..`、反斜杠映射，以及 generation 根/资源文件符号链接和越界文件；保留候选/Git cache 不可读取的测试。
  - 复查 lease 发布顺序、旧 generation 回收和 listener 快照遍历，发现 `_activate()` 在 listener 抛错时会跳过 `_collect_retired()`，导致无 lease 的旧 generation 残留；按 TDD 增加失败测试并用 `try/finally` 修复，仍保留 listener 原异常和已发布 snapshot 语义。
  - 静态审计确认主要 renderer 和 legacy utils 仍直接消费插件 `src/resources` 物理路径；这是 Task 07–09 的既定迁移范围，本 task 未提前扩大。
- 验证证据：
  - Red：新增 `test_listener_failure_still_collects_retired_generation` 后实际失败，旧 generation 目录仍存在（断言失败）；修复后该测试 `1 passed`。
  - 资源/generation/config/operations/renderer 相关回归：`50 passed`，命令为 `PYTHONPATH=. /Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest --confcutdir=tests tests/test_goal5_asset_resolver.py tests/test_goal3_resource_generations.py tests/test_config_resources.py tests/test_operations.py tests/test_rendering_assets.py -q`。
  - 首轮包含 `tests/test_player.py` 的扩展回归为 `59 passed, 2 failed`；两个失败均来自本机 T2I 渲染返回 `Client Closed Request`，失败位置为 `tests/test_player.py::test_role_detail_renders_all_basic_sections_and_original_path` 与 `tests/test_player.py::test_concurrent_role_details_keep_their_related_original_paths`，不是资源/generation 断言。测试 fixture 将端点固定为 `http://127.0.0.1:8999/text2img`，当前环境该路径返回 404/关闭请求，作为环境阻塞记录，不改业务逻辑。
  - 变更文件 LSP diagnostics 为空；目标 Ruff、相关 compileall、`git diff --check` 均通过。测试仅产生既有 `audioop` deprecation warning。
- 新增修复 task：无；listener 清理问题已在本 task 内修复并纳入提交。
- 剩余风险：主要 renderer 尚未消费 logical key/resolver；动态角色/武器/面板 key 的 snapshot 映射、实际 placeholder bytes、`incomplete` 在用户响应中的传递仍由 Task 07–09 完成。完整字体/大型纹理删除前仍需资源仓库 manifest/SHA 与发布包证据。
- 下一步建议：执行 Task 07，先为 Player、百科、签到、公告和 Help 的 resolver 接入与降级路径建立 Red 测试。

## Task 07 — Player/Encyclopedia/Checkin/Notices/Help 字体与纹理接入 Red `[completed]`

**目标**：测试先行锁定主要 renderer 使用统一 resolver、无本地完整字体时不启动失败、缺失资源能简化渲染并标记 `incomplete`。

**范围**：相关领域 renderer、`load_runtime_font()`、旧 utils 路径的测试；只新增/扩展测试。

**验收**：Red 测试实际失败；覆盖 Player、Encyclopedia、Checkin、Notices、Help 代表路径，至少覆盖启动加载、字体回退、纹理缺失、角色/武器/面板来源和 snapshot 刷新。

- 实际做了什么：
  - 新增 `tests/test_goal5_renderer_resolver_red.py`，使用不触碰网络/T2I 的 `RecordingResolver` 与最小 JPEG fake，冻结 renderer 的请求级 resolver 注入和缺失资源语义。
  - 覆盖 `load_runtime_font()` 在完整本地字体不存在时仍返回可用字体；覆盖 Player 总览的角色头像/武器 key、详情的立绘/panel key、缺失资源 `incomplete` 以及 generation 切换后的重新解析。
  - 覆盖 Encyclopedia 周报/活动日历、Checkin 签到日历、Notices 公告列表的字体/纹理缺失与 `incomplete`；覆盖 Help 接受 resolver 并解析帮助字体/纹理。
- 验证证据：
  - Red 阶段实际执行：`PYTHONPATH=. /Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest --confcutdir=tests tests/test_goal5_renderer_resolver_red.py -q --tb=short`，退出码 `1`，结果为 `7 failed, 1 warning`。
  - 失败均对应当前生产缺口：字体回退仍抛 `OSError: cannot open resource`；Player/Encyclopedia/Checkin/Notices 未调用 resolver（实际请求为空）；Help 尚不接受 `asset_resolver` 参数并抛 `TypeError`。未把 Red 失败伪装成跳过或成功。
  - `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/ruff check tests/test_goal5_renderer_resolver_red.py`、`python3 -m compileall -q tests/test_goal5_renderer_resolver_red.py`、`git diff --check` 通过；Python LSP 对新增测试文件无诊断。
- 剩余风险：生产 renderer 和旧 utils 仍未迁移到统一 resolver；除 Player 外的渲染结果尚未有明确 `incomplete` 字段；完整 snapshot 的真实素材读取、placeholder bytes、缓存和 listener 刷新仍需 Green/集中审计验证。本 task 测试按设计保持 Red。
- 下一步建议：执行 Task 08，实现最小请求级 resolver 接入、字体安全回退、纹理/角色/武器/panel 缺失简化渲染和各 renderer 的 `incomplete` 传递，再将本 task 转 Green。

## Task 08 — 主要 renderer 与 legacy 路径 Green 迁移 `[completed]`

**目标**：将主要渲染链路切到统一逻辑 key，消除插件目录硬编码资源依赖，同时保持完整 snapshot 与降级路径行为。

**范围**：`src/infrastructure/rendering/`、`src/modules/{player,encyclopedia,checkin,notices}/`、Help、必要的 `src/utils/`/`dnaby/` 适配；不删除资源文件。

**验收**：Task 07 转 Green；静态检索确认主要 renderer 不再拼接待外置资源的插件路径；不资源同步时无 `FileNotFoundError`，完整 snapshot 时能读取远端资源；listener 后无需重启刷新。

- 实际做了什么：
  - 新增 `src/infrastructure/rendering/runtime_assets.py`，统一封装 resolver 结果、可见 placeholder、PIL 简化卡片、字体/图片 data URI 和 `incomplete` 记录；resolver 注入后不再回读 legacy 路径。新增 `legacy_assets.py` 只集中兼容路径常量，不改变资源删除边界。
  - 扩展 `RuntimeAssetResolver` 的显式 wildcard 映射，补齐角色头像/立绘、武器、panel、周报、日历及主要 renderer 纹理 key；bootstrap 只登记映射，不扫描目录。`ResourceSnapshotCoordinator.bind_renderer()` 在既有 generation lease 内复制 renderer 并创建请求级 resolver，保留同步后新请求读取新 generation、旧请求 pin 旧 generation 的语义。
  - Player、Encyclopedia、Checkin、Notices（含密函、公告列表、公告详情）在 resolver 模式下统一读取逻辑 key，缺失资源生成确定性简化 JPEG 并标记 `incomplete=True`；完整 snapshot fixture 能读取同一远端素材并保持 `incomplete=False`。Help 通过 `bind_resource_resolver` 注入 resolver，并在 resolver 模式绕过旧缓存，避免跨 generation 复用模板素材。
  - `load_runtime_font()` 在显式字体和 bundled 字体不可用/损坏时回退 Pillow 内置字体；独立签到广播卡的字体 URI 也改为安全 fallback。`payloads.py`、`weapon_renderer.py` 的兼容常量统一收口，未删除任何资源文件。
- 验证证据：
  - TDD Red：新增公告详情 resolver 与签到广播缺失字体契约后，分别实际运行并确认旧实现失败（详情调用 legacy 绘制、缺失字体抛 `AssetRenderError`）；实现后同一测试转绿。
  - 目标回归：`PYTHONPATH=. /Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest --confcutdir=tests tests/test_goal5_asset_resolver.py tests/test_goal5_renderer_resolver_red.py tests/test_goal3_resource_generations.py -q --tb=short`，`39 passed, 1 warning`。
  - 相关 HTML/renderer 回归：`tests/test_html_card_payloads.py`、Player/Encyclopedia/Notices 资源状态测试共 `9 passed, 1 warning`。
  - 完整 snapshot fixture 冒烟覆盖 Player 总览/详情、百科周报/日历、签到、密函、公告列表/详情共 8 个结果：均生成非空图片、`incomplete=False`，实际记录 25 个 resolver key；该 fixture 使用临时已验证图片模拟 snapshot，不冒充资源仓库完整素材验证。
  - `python3 -m compileall -q src tests/test_goal5_renderer_resolver_red.py`、变更文件范围 `ruff check`、`git diff --check` 通过。全仓 `ruff check .` 仍报告既有脚本/旧测试等 25 个 lint 问题，未归因于本 task，未对无关文件做格式化。
  - 静态检索主要 renderer 已无插件目录资源路径拼接；仅保留 `fonts.py` 的安全 bundled-font 探测、`ResourceMap` 对已绑定 snapshot root 的相对路径访问，以及 sidecar 历史来源字符串。未删除 `src/resources/`，因此后续 Task 10–12 仍需资源仓库证据和包体积验证。
- 剩余风险：当前 `dna-resource` HEAD 尚未提供本 task 所有纹理族及 `file_hashes`/完整 manifest 证据；真实远端 generation 仍需后续资源仓库 task 验证。无 resolver 的 legacy helper 仍保留用于兼容，真实 T2I 服务缺失时相关旧路径测试会失败（已有环境性失败，不代表 resolver 分支回归）。全仓 lint 的 25 个既有问题也仍待集中处理。
- 下一步建议：执行 Task 09，集中审计 renderer/legacy utils 的所有路径与逻辑 key、缓存 `incomplete`、lease/listener、placeholder 和异常可观测性，再决定资源仓库及删除 task 的准入条件。

## Task 09 — Renderer 接入与 incomplete 语义集中检查 `[completed]`

**类型**：集中检查-debug（Task 07–08）。

**检查**：逐模块审计 Player/百科/签到/公告/帮助/legacy utils 的路径和逻辑 key，验证缓存 incomplete、snapshot lease、listener、占位图/简化渲染、异常可观测性和无新增依赖；必要时追加修复 task。

- 实际检查：
  - 审计 Player/百科/签到/公告/帮助的 resolver 分支、逻辑 key、placeholder/fallback 状态和缓存行为；帮助卡现在会把 resolver 资源记录写入 artifact sidecar，并以 `ImageResponse.incomplete` 暴露不完整资源，resolver 模式继续绕过旧缓存。
  - 修复 Player/百科/公告 legacy font fallback 缺少 `incomplete` 字段的问题；`resources_incomplete` 现在优先读取显式字段，并兼容旧的 `fallback`/`missing`/`placeholder` 状态。
  - 复核 `ResourceSnapshotCoordinator` 的 request-level lease、`bind_renderer` 和 generation listener；既有 lease/listener 契约未发现需要在本 task 改动的问题。
  - 复核 legacy utils：`src/utils/image.py` 仍会延迟导入 `src/utils/fonts/dna_fonts.py`，而后者在模块导入时 eager 构造字体对象；这仍是后续删除旧字体目录前的明确前置条件。
  - 复核逻辑 key 与资源仓库契约：当前 `textures` 未进入 runtime manifest/validator 根目录，且若干 dotted texture wildcard 尚未和资源仓库中的实际文件名对齐，因此没有伪造完整 snapshot。
- 验证证据：
  - TDD Red：新增 `tests/test_goal5_task09_audit.py` 后首次运行出现 3 个预期失败（fallback incomplete 语义、legacy renderer 字体记录、帮助卡 resolver 资源状态）。
  - Green/regression：`tests/test_goal5_task09_audit.py tests/test_goal5_asset_resolver.py tests/test_goal5_renderer_resolver_red.py tests/test_goal3_resource_generations.py tests/test_generated_image_lifecycle.py tests/test_html_card_payloads.py`，`50 passed, 1 warning`。
  - `python3 -m compileall -q src tests/test_goal5_task09_audit.py` 通过。
  - 变更文件定向 `ruff check` 通过；`git diff --check` 通过。
  - `requirements.txt` 未变更，无新增依赖。
- 新增修复 task：
  - Task 10/11 前置：将 `src/utils/fonts/dna_fonts.py` 的 eager 字体导入迁移到安全的 runtime font resolver，再允许删除旧字体目录。
  - Task 10/11 共同契约：把 `textures` 纳入 runtime manifest/validator 与解码/hash 测试；按 `dna-resource` 的实际文件名重做 dotted texture key 的精确映射；明确 Help 小资源/logo 的 bootstrap allowlist 或 placeholder 语义。
- 剩余风险：
  - `dna-resource` 当前尚无 `textures` 目录和 `file_hashes` 证据，远端资源与 wildcard 映射尚未验证。
  - 旧 renderer 的完整回归仍有 24 个依赖本机 `http://127.0.0.1:8999/text2img` 的环境失败；本 task 的 focused resolver/audit 回归不受影响。

## Task 10 — `dna-resource` 补齐字体/大型纹理并更新 manifest `[completed]`

**目标**：在资源仓库中补齐完整字体变体和已确定外置纹理，写入 `file_hashes` 并更新 `resource_version`，以现有 validator 验证可发布 generation。

**范围**：独立的 `dna-resource` 工作区/分支（若可访问）；不把私有资源复制到插件仓库，不在插件仓库伪造资源文件。

**验收**：资源仓库变更可独立提交；关键字体文件头、图片可解码、SHA-256、manifest 和 generation validator 全部通过；若仓库不可访问，task 明确标记阻塞并把可继续的插件侧工作与发布风险写清楚。

- 实际做了什么：
  - 在 `codex/resource-slimming-design-resource` 资源工作区提交 `2e31eb3b7bb112e2a105d89cbf55fccc52dbd1f0`：补齐 manifest 所需的 7 个关键字体变体（本 task 新增缺失的 `MiSansVF.woff2`、两个 `arial-unicode-ms-bold` WOFF2 变体和 `dna_fonts.woff2`）、9 个 calendar 素材，以及 `textures/{ann,common,detail,help,mh,role,sign,stamina}` 共 111 个共享纹理；未把这些资源复制回插件仓库。
  - 更新 `resource_manifest.json`：`required_dirs` 纳入 `textures`，`resource_version` 更新为 `redeem-code-v1-resource-slimming-2026-09-08`，为 127 个文件写入 SHA-256 `file_hashes`。
  - 在 `codex/resource-texture-contract` 编辑器工作区提交 `66a3b85`：资源路径契约识别共享纹理、named panel、可选 SHA-256 manifest 字段，并允许资源仓库现有维护文档。
  - 插件工作区纳入 `textures` generation/manifest 校验和真实文件名 resolver 映射；公告 list/detail 在当前资源仓库仅有官方头像素材时共用 `dna_official_avatar.jpeg`，不伪造不存在的独立图片。
- 验证证据：
  - TDD Red 阶段新增纹理目录、图片解码、资源契约和 resolver 映射测试均按预期失败；Green 后插件 focused pytest 为 `50 passed, 1 warning`。
  - 编辑器 `npm run test:worker`：`7` 个文件、`101` 个测试通过；`npm run test:ui`：`10` 个文件、`87` 个测试通过；`npm run typecheck` 通过；实际资源树的 validator 临时集成检查通过。
  - 插件变更文件 `compileall`、定向 `ruff check`、`git diff --check` 全部通过；无新增依赖。
  - 以资源提交的完整 SHA 校验 generation：manifest/hash `127` 项、图片 `120` 个全部可解码、7 个字体头分别符合 TTF/WOFF2、generation `content_sha256=bba25183cf7264764fd007004ecf19f5cde867e6f05e288c1ff8dcda4e04b5ab`。
- 剩余风险：
  - 资源分支和编辑器分支目前只在本地 worktree，尚未 push/开 PR/合并；发布顺序仍必须先合并 `dna-resource`，再合并插件。
  - Task 11 尚未删除插件内重复字体和已接管的大型纹理，因此本 task 不代表最终插件包体积已达标；`weekly_report` 小图标仍按范围保留在插件侧。
  - `ann.list` 与 `ann.detail` 当前共用官方头像是可验证的降级装饰素材，不等价于两套独立公告美术资源；若上游提供独立素材，需后续补充映射和 hash。
  - 旧 renderer 全量回归仍有 24 个依赖本机 `127.0.0.1:8999/text2img` 的环境失败，本 task 的资源 focused 验证不受影响。
- 下一步建议：执行 Task 11，删除前先完成插件重复字体/纹理的静态引用审计，并保留 bootstrap allowlist 与无 snapshot 降级验证。

## Task 11 — 删除重复字体与已接管的大型纹理 `[completed]`

**目标**：在 resolver、renderer 和资源仓库证据齐备后，删除插件内重复/完整字体树及由 `dna-resource` 接管的大型纹理，仅保留 bootstrap allowlist。

**范围**：`src/resources/`、`src/utils/fonts/`、已确认迁移的 `textures/{calendar,common,detail,role,...}`；同步更新必要的资源清单/文档，不扩大到小图标。

**验收**：删除前静态引用审计无待删除路径消费者；目标资源在 verified snapshot 中可验证；插件导入/启动/无 snapshot 降级不抛 `FileNotFoundError`；未删除的 bootstrap 资源有清单和理由。

- 实际做了什么：删除 `src/resources/fonts/` 与重复的 `src/utils/fonts/`，以及已由资源仓库接管的 `textures/{ann,calendar,common,detail,guide,help,mh,role,sign,stamina,wiki}`；保留 `src/resources/help/` 的帮助数据/图标、`src/resources/textures/weekly_report/` 和 `src/utils/texture2d/` 的小型 bootstrap 装饰素材。将 allowlist 收敛为 `texture.common.number.{0..10}`，并把 profile/header、legacy renderer 与字体加载改为本地 bootstrap、verified snapshot 或可见 placeholder/Pillow fallback；同步修正无 snapshot 回归测试和日历最小 fixture。
- 验证证据：Task 11 测试先行 Red 阶段实际得到 6 个预期失败；资源仓库 `2e31eb3b7bb112e2a105d89cbf55fccc52dbd1f0`（`redeem-code-v1-resource-slimming-2026-09-08`）的 127 个 `file_hashes` 全部匹配，120 个日历/纹理图片可由 Pillow 解码，7 个字体文件头有效。插件 focused 回归 `144 passed, 1 warning`，资源仓库契约测试在显式 `DNA_RESOURCE_REPO` 下 `6 passed`；`compileall`、本次变更文件 `ruff check` 与 `git diff --check` 均通过。删除后的静态审计仅保留兼容常量和安全 fallback 封装，没有未兜底的待删除资源直接读取。
- 剩余风险：资源仓库提交必须先于插件版本发布；旧独立 helper 在无 snapshot 时会使用 placeholder/Pillow fallback，完整视觉效果依赖 verified snapshot。旧 renderer 全量回归仍有 24 个依赖本机 `127.0.0.1:8999/text2img` 的环境失败，非本 task 资源逻辑失败。
- 下一步建议：执行 Task 12，集中检查全量静态路径/逻辑 key、发布包体积与最大剩余文件，并收口删除后的资源边界。

## Task 12 — 资源删除与体积集中检查 `[completed]`

**类型**：集中检查-debug（Task 10–11）。

**检查**：运行全量静态路径/逻辑 key 搜索、目标测试/compile/lint/加载检查，构建真实市场发布包并记录体积；检查 `<=8 MiB`、`<=12 MiB`、`<16 MiB` 判定与最大剩余文件，发现回归或超标就追加最小修复/下一批纹理迁移 task。

- 实际检查：以 Task 11 提交 `8b1a450274b9d1c747cc7d469f0e4e071cc785b7` 为输入，复核 13 个已删除字体/纹理根均不在 tracked tree；全量检索了旧物理路径、文件名、legacy 常量、snapshot logical key 和 runtime `Image.open` 调用。构建了当前仓库唯一可复现的提交 ZIP（仓库没有专用市场打包脚本）；该保守包包含测试、文档和 goal 记录，未采用未经证实的市场端排除规则。
- 验证证据：提交 ZIP 共 543 个文件，压缩包 `3,292,638 bytes / 3.140104 MiB`，ZIP 成员压缩总量 `3,195,230 bytes / 3.047209 MiB`，未压缩总量 `6,043,038 bytes / 5.763090 MiB`，因此同时满足 `<=8 MiB`、`<=12 MiB` 和 `<16 MiB`。最大剩余文件为 `src/utils/texture2d/bg.jpg`（408,490 bytes，0.389566 MiB），其次为 `avatar_title_bg.png`（340,740 bytes）和 `bg2.jpg`（232,350 bytes）；包内无已删除大资源根。目标 focused 回归为 `144 passed, 1 warning`；完整 pytest 为 `1032 passed, 1 skipped, 12 failed, 3 subtests passed`，失败均已归类为宿主端口 `6189` 被占用、缺失被忽略的 `tests/.data`、默认指向旧资源 checkout、旧 editor checkout/缺失 Vitest、以及既有 cache/help/import 契约，不属于 Task 11 变更。使用资源仓库 `2e31eb3b7bb112e2a105d89cbf55fccc52dbd1f0` 与 AstrBot `v4.26.5` 本地 tag 的官方 loader 检查分别通过：资源 contract/resolver 在显式资源路径下通过，插件 `load + initialize` 注册 `63` 个 command/handler，`terminate` 成功。`compileall`、变更文件 `ruff check`、pre-commit ruff 和 `git diff --check` 通过；全仓 ruff 仍报告 25 个既有非本 task 违规，未出现在本次变更文件中。
- 新增修复 task：无。Task 11 变更没有引入资源路径、包体积或官方加载回归；跨仓 editor contract 失败留作资源仓库/editor 分支先行交付顺序的风险记录，不在本插件 task 内安装新依赖或修改其他仓库。
- 剩余风险：仓库没有可在本地确认的官方市场后端过滤规则，3.140104 MiB 是包含开发文件的保守 source-archive 上界；最终仍需在 Task 16 按最终提交重新测量。完整 pytest 的 12 个非资源失败需要在宿主端口、ignored fixture、资源仓库/editor checkout 和既有测试基线恢复后复核；当前不应将其误报为本 task 全绿。资源仓库必须先于插件发布，editor worktree `codex/resource-texture-contract` 还缺独立 `node_modules/vitest`，未安装新依赖以保持环境不变。

## Task 13 — README 与资源使用/维护文档同步 `[completed]`

**目标**：同步首次安装“建议执行同步资源”提示和当前资源边界、降级语义、维护/回滚说明。

**范围**：`README.md`、`docs/usage/resources.md`、必要的 `docs/dev/maintenance.md`、`docs/project/architecture.md`；不创建无关文档。

**验收**：README `> [!IMPORTANT]` 明确建议、非强制；文档描述 verified snapshot/bootstrap/placeholder/incomplete、首次同步、无重启刷新、资源仓库先行和回滚；不承诺不存在的 CI 或自动同步。

- 实际做了什么：在 `README.md` 安装步骤后加入 `> [!IMPORTANT]` 提示，明确首次安装后建议但不强制执行 `kk资源状态`/`kk下载全部资源`；说明无 verified snapshot 时仍可启动、图片结果可能是 `placeholder`/`fallback` 且标记 `incomplete`，同步成功后无需重启即可使用新 generation。更新 `docs/usage/resources.md`，补充 verified snapshot → bootstrap → placeholder/none 的解析顺序、本地 bootstrap 边界、首次同步、资源仓库 `main` 先行、校验失败保留旧快照和 `git revert` 回滚；同步在 `docs/dev/maintenance.md`、`docs/project/architecture.md` 中的发布前置、listener/lease 刷新和解析器职责。没有承诺不存在的 CI 自动发布或安装强制前置条件。
- 验证证据：文档契约脚本确认重要提示、非强制措辞、同步命令、四类资源状态和无重启刷新说明均存在；`tests/test_goal5_docs_audit.py tests/test_goal5_ci_contracts.py` 为 `22 passed`，覆盖公开文档相对链接、README 链接、配置字段和内部残留；`git diff --check` 通过。仅修改文档与本 task 记录，未改变运行时代码或依赖。
- 剩余风险：文档按当前插件/资源仓库契约描述行为；资源仓库与 editor 分支仍需按三仓顺序先行交付，真实运行期无 snapshot/完整 snapshot/同步刷新验证留给 Task 14，最终集中审计留给 Task 15–16。
- 下一步建议：执行 Task 14，使用隔离 fixture 完成无 snapshot、完整 snapshot 和同步后无需重启刷新冒烟验证。

## Task 14 — 无 snapshot / 完整 snapshot / 同步刷新运行期验证 `[completed]`

**目标**：用现有 fixture/fake 或本地可验证资源执行两种 snapshot 场景和同步后刷新冒烟，不访问真实生产账号，不提交资源内容。

**范围**：资源/generation/renderer 测试、插件加载检查、必要的最小运行脚本；不自动同步、不修改生产数据。

**验收**：无 verified snapshot 可启动、基础命令可执行、图片命令不因缺失资源崩溃并产生 `incomplete`；完整 snapshot 恢复主要渲染；发布新 generation 后无需重启使用新资源；取消/失败/非 2xx 等现有错误语义未被吞掉。

- 实际做了什么：使用 pytest 临时目录和 fake resource service 验证无 verified snapshot 的 `build_runtime` 初始化、资源视图为空、预热/终止生命周期和基础命令 registry；资源 renderer 使用现有缺失资源 fixture 验证图片命令不抛 `FileNotFoundError`，而是产生 `placeholder`/`fallback` 与 `incomplete`。使用 `test_goal3_resource_generations.py` 的本地 Git fixture 验证完整 generation 发布、重启恢复、旧 generation lease、listener 刷新和失败保留旧快照；未访问真实账号、生产数据或提交资源内容。为避免开发机 `127.0.0.1:6189` 占用干扰资源生命周期测试，将该测试显式配置为已支持的临时端口 `login.port=0`，不改变生产默认配置。
- 验证证据：资源/renderer/generation/loader/lifecycle/cache/命令 focused 回归 `101 passed, 1 warning`；资源仓库显式 `DNA_RESOURCE_REPO` contract 为 `6 passed`；官方 AstrBot `v4.26.5` 本地 tag loader 为 `load + initialize: success (commands=63, handlers=63)`、`terminate: success`。另执行无 snapshot lifecycle smoke（资源 root/player resources 均为空，preheat `start/stop` 成功）；resolver/renderer 测试覆盖缺失资源 `incomplete`、完整 snapshot 优先级和新 generation 读取；`ResourceUpdateService` 测试覆盖取消、同步失败、Git/候选错误、非成功同步结果的可见性与 single-flight。所有验证使用隔离临时目录/fake，不执行真实同步。
- 剩余风险：完整 snapshot 的视觉质量仍依赖资源仓库 `main` 的实际素材和外部 T2I/账号环境；当前已验证的是资源 manifest/fixture、resolver 和主要 renderer 降级/刷新契约，不宣称真实生产图片验收。资源仓库与 editor 分支仍需按三仓顺序交付；全 goal 的最终规格偏差、敏感信息、包体积和回滚集中审计留给 Task 15–16。
- 下一步建议：执行 Task 15，集中检查运行期边界、文档/安全/回滚、三仓交付顺序和规格偏差。

## Task 15 — 运行期、文档、安全与回滚集中检查 `[completed]`

**类型**：集中检查-debug（Task 13–14）。

**检查**：核对规格偏差、静态引用/死代码、依赖和敏感信息、运行期数据目录、并发/缓存/manifest 一致性、README/docs、回滚路径和两个仓库交付顺序；发现问题追加修复 task。

- 实际检查：
  - 复核规格完成定义与当前实现：已删除的 13 个字体/大型纹理本地根均不存在；生产源码没有 `gsuid_core`/`gsucore` import；旧文件名只保留在 `_SNAPSHOT_ASSET_PATHS`、sidecar 来源字符串、legacy 兼容常量和测试中。注入 resolver 后 renderer 不回读 legacy path，资源解析仍固定为 verified snapshot → 显式 bootstrap → placeholder/none。
  - 复核运行期目录边界：新资源仓库、generation 指针、`rendered/`、`cache/`、数据库、订阅和公告状态均从 AstrBot 数据目录/数据库父目录派生；没有新增插件源码目录写入。旧 `RESOURCE_PATH.py` 兼容模块仍通过 AstrBot 全局数据根初始化历史子目录，但不写入源码树，列为低风险遗留边界。
  - 复核并发、lease、listener、缓存和 manifest：single-flight、取消/失败可见性、generation lease/listener、placeholder 不进入完整缓存和 manifest 路径/hash 校验均已有 focused 覆盖；实现没有新增固定超时或静默成功回退。资源工作区 manifest 声明 13 个 required directories，127 个 file hash 均无缺失/不匹配/孤立项。
  - 复核依赖、敏感信息和回滚：`requirements.txt`/构建依赖无 diff；tracked tree 没有 `.env`、Cookie/token、SQLite、日志或凭据内容，命中 `app_credentials_only`/`secret_cache` 仅为迁移文件名和测试名；每个迁移 task 保留独立 commit，可按资源仓库 → editor contract → 插件顺序交付或逐 commit revert。
  - 复核文档和跨仓交付顺序：README 的首次同步提示明确为“建议、非强制”，资源使用文档描述 snapshot/placeholder/incomplete、无重启刷新和回滚；当前插件 `001ca7d`、资源仓库 `2e31eb3`、editor `66a3b85` 均位于独立干净 worktree，尚未 push/合并，发布仍需资源仓库先行。
  - 发现两项同一根因的可执行缺口：Help 的 `texture.help.logo`、`texture.help.icon:*` 未进入 bootstrap allowlist，运行期 resolver 会把仓库中仍保留的 logo/帮助小图标解析为 `none/placeholder/incomplete`；`docs/usage/resources.md` 的 manifest 示例也遗漏已成为 runtime contract 的 `textures` 目录。
- 验证证据：
  - 使用显式 `DNA_RESOURCE_REPO=/Users/flanchan/Developer/Projects/GithubProjects/.worktrees/astrbot_plugin_dna_resources-resource-slimming-design` 运行资源/文档/清理/治理/解析器/资源契约 focused suite：`53 passed, 1 warning`；未设置该变量时的唯一失败是宿主默认旧资源 checkout 缺少 `schemas`/`textures`，已确认是环境选择问题而非插件实现失败。
  - 变更运行时代码定向 `ruff check`、`git diff --check` 和 LSP diagnostics（bootstrap、manifest、generation、resolver、runtime_assets）均通过；资源 manifest 独立 SHA-256 核验通过。静态 smoke 明确复现上述 Help 缺口：`texture.help.logo`、`texture.help.icon:状态`、`font.help` 在无 snapshot 时均为 `none/missing/incomplete=True`，数字 bootstrap 仍按既有契约工作。
- 发现并已在 Task 15A 修复两项同一根因的可执行缺口：Help 的 `texture.help.logo`、`texture.help.icon:*` 未进入 bootstrap allowlist，运行期 resolver 会把仓库中仍保留的 logo/帮助小图标解析为 `none/placeholder/incomplete`；`docs/usage/resources.md` 的 manifest 示例也遗漏已成为 runtime contract 的 `textures` 目录。
- 剩余风险：资源仓库和 editor 分支仍只存在本地 worktree，最终市场包需在 Task 16 重新测量；完整 pytest 的宿主端口、ignored fixture、旧 checkout/T2I 环境失败仍不应误报为资源目标全绿。Help bootstrap 采用静态显式文件名清单，后续若保留图标集合变化需同步更新 allowlist 与契约测试。

## Task 15A — 修复 Help bootstrap 资源契约与 manifest 文档 `[completed]`

**目标**：让规格明确保留的 `ICON.png`/Help 必要小图标在 resolver 模式下通过显式 bootstrap allowlist 工作，不因没有 verified snapshot 被误标 `incomplete`；同步修正资源 manifest 文档示例。

**范围**：`src/bootstrap.py`、`src/infrastructure/resources/resolver.py`、Help 逻辑 key/测试、`docs/usage/resources.md` 和本 task 记录；不得递归扫描本地资源目录，不引入新依赖，不改变完整 snapshot 优先级。

**验收**：TDD Red → Green 覆盖 logo、实际 Help icon filename、无 snapshot Help 资源记录和 completeness；显式 bootstrap 仍拒绝未登记路径；文档示例包含 `textures`；相关 pytest、compile、ruff 和 diff 检查通过。

- 实际做了什么：在 `src/bootstrap.py` 增加静态显式的 47 个 Help icon filename、`ICON.png` logo 和既有数字纹理 bootstrap 映射；在 resolver 中把 logo 与 `texture.help.icon:` 前缀标记为完整 fallback，同时保留未登记 icon、缺失 `font.help` 的 `none/missing/incomplete` 语义；Help renderer 的逻辑 key 改为使用实际解析到的 icon filename，避免 alias/fallback 名称与 allowlist 脱节；manifest 文档示例补充 `textures`。未递归扫描本地资源目录、未引入依赖、未改变 verified snapshot 优先级。
- 验证证据：先运行 TDD Red，目标 suite 以 `33 passed, 4 failed` 证明缺口；实现后运行相同 focused suite 为 `37 passed, 1 warning`；覆盖 `ICON.png`、真实 `日常.png`、未登记 icon、无 snapshot completeness、Help 实际 key 和 `textures` 文档示例。`compileall -q`、定向 `ruff check`、`git diff --check` 和受影响 Python 文件 LSP diagnostics 均通过。
- 剩余风险：完整 pytest 的既有宿主端口、ignored fixture、旧资源 checkout/T2I 环境失败仍留给后续统一复核；Help 的字体仍需 verified snapshot 或显式供给，bootstrap 只保证规格保留的 logo/小图标。最终发布包仍需 Task 16 按最终提交重新测量。

## Task 16 — 最终发布包测量与证据收口 `[completed]`

**目标**：按真实市场提交方式生成最终插件包，记录体积、构成和阈值结论，确保没有完整大字体副本或私有文件。

**范围**：既有打包脚本/构建产物、`git ls-files`/归档内容、相关验证日志；不新增 CI。

**验收**：包可复现；字节数/MiB 明确；`<=8 MiB` 或有理由的 `<=12 MiB`，且 `<16 MiB`；最大剩余文件列出并说明保留理由；静态路径与测试证据附在 task 记录。

- 实际做了什么：以插件提交 `71f7bef` 为输入，使用仓库现有可验证的最接近市场提交方式 `git archive --format=zip --prefix=astrbot_plugin_dnaby/ 71f7bef` 生成保守 source archive。仓库没有专用市场打包脚本或已确认的服务端排除规则，因此没有臆造过滤条件；归档只包含 `git ls-files`，不包含工作树缓存、`.git` 或 ignored 文件。
- 验证证据：归档包含 543 个文件，压缩包 `3,326,076 bytes / 3.171993 MiB`，ZIP 成员压缩总量 `3,202,576 bytes / 3.054214 MiB`，未压缩总量 `6,064,222 bytes / 5.783293 MiB`，同时满足 `<=8 MiB`、`<=12 MiB` 和 `<16 MiB`。同一提交重复生成归档结果逐字节一致，SHA-256 为 `7ae9897ef99739b3aedd43af9f1a39d6960dcffe8aefbe9c53312c6457d6d943`。最大运行期保留文件为 `src/utils/texture2d/bg.jpg`（408,490 bytes）、`avatar_title_bg.png`（340,740 bytes）和 `bg2.jpg`（232,350 bytes），均属于 Task 11 保留的少量 bootstrap 装饰；`ICON.png`/`logo.png` 各 117,194 bytes 为品牌资源。其余较大的 `goal-*/tasks.md` 与测试 fixture 是保守 source archive 的开发记录/测试内容，不是运行期资源。归档无 `.env`、`.git`、`__pycache__`、`.venv`、已删除字体/大型纹理根或实际凭据内容；Task 15A 相关回归为 `58 passed, 1 warning`，并已有 compileall、ruff、LSP diagnostics 与静态路径审计证据。
- 剩余风险：仓库没有可本地确认的官方市场后端过滤规则，实际市场端若排除开发文档/测试文件，最终包只会更小；本记录采用保守上界而非未经证实的市场过滤模型。资源仓库和 editor worktree 仍需按两仓库先行顺序交付，最终整体完成性留给 Task 17 终审。
- 下一步建议：执行 Task 17，从规格完成定义逐项复核资源仓库、运行期 snapshot/降级、同步刷新、文档、测试、回滚和发布证据。

## Task 17 — Goal 终审与完成登记 `[pending]`

**类型**：终审。

**检查**：从 C 端体验、代码质量、资源安全、manifest/generation、缓存刷新、无/有 snapshot、错误处理、测试覆盖、构建产物、文档和回滚角度进行最大范围复查。所有已知高风险问题必须修复或明确阻塞；确认 tasks.md 所有 task 已完成/阻塞并填写证据后，登记 goal 完成。

- 实际检查：待填。
- 验证证据：待填。
- 阻塞/低风险事项：待填。
- 最终报告要点：待填。
