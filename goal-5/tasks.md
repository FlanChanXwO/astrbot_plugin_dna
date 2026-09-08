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

## Task 06 — 解析边界集中检查 `[pending]`

**类型**：集中检查-debug（Task 04–05）。

**检查**：复查 resolver API 深度、来源优先级、路径安全、None/placeholder/incomplete 语义、快照租约和 listener 并发边界；运行资源/generation/现有 renderer 回归，发现问题就在 tasks.md 末尾追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 07 — Player/Encyclopedia/Checkin/Notices/Help 字体与纹理接入 Red `[pending]`

**目标**：测试先行锁定主要 renderer 使用统一 resolver、无本地完整字体时不启动失败、缺失资源能简化渲染并标记 `incomplete`。

**范围**：相关领域 renderer、`load_runtime_font()`、旧 utils 路径的测试；只新增/扩展测试。

**验收**：Red 测试实际失败；覆盖 Player、Encyclopedia、Checkin、Notices、Help 代表路径，至少覆盖启动加载、字体回退、纹理缺失、角色/武器/面板来源和 snapshot 刷新。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 08 — 主要 renderer 与 legacy 路径 Green 迁移 `[pending]`

**目标**：将主要渲染链路切到统一逻辑 key，消除插件目录硬编码资源依赖，同时保持完整 snapshot 与降级路径行为。

**范围**：`src/infrastructure/rendering/`、`src/modules/{player,encyclopedia,checkin,notices}/`、Help、必要的 `src/utils/`/`dnaby/` 适配；不删除资源文件。

**验收**：Task 07 转 Green；静态检索确认主要 renderer 不再拼接待外置资源的插件路径；不资源同步时无 `FileNotFoundError`，完整 snapshot 时能读取远端资源；listener 后无需重启刷新。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 09 — Renderer 接入与 incomplete 语义集中检查 `[pending]`

**类型**：集中检查-debug（Task 07–08）。

**检查**：逐模块审计 Player/百科/签到/公告/帮助/legacy utils 的路径和逻辑 key，验证缓存 incomplete、snapshot lease、listener、占位图/简化渲染、异常可观测性和无新增依赖；必要时追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 10 — `dna-resource` 补齐字体/大型纹理并更新 manifest `[pending]`

**目标**：在资源仓库中补齐完整字体变体和已确定外置纹理，写入 `file_hashes` 并更新 `resource_version`，以现有 validator 验证可发布 generation。

**范围**：独立的 `dna-resource` 工作区/分支（若可访问）；不把私有资源复制到插件仓库，不在插件仓库伪造资源文件。

**验收**：资源仓库变更可独立提交；关键字体文件头、图片可解码、SHA-256、manifest 和 generation validator 全部通过；若仓库不可访问，task 明确标记阻塞并把可继续的插件侧工作与发布风险写清楚。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 11 — 删除重复字体与已接管的大型纹理 `[pending]`

**目标**：在 resolver、renderer 和资源仓库证据齐备后，删除插件内重复/完整字体树及由 `dna-resource` 接管的大型纹理，仅保留 bootstrap allowlist。

**范围**：`src/resources/`、`src/utils/fonts/`、已确认迁移的 `textures/{calendar,common,detail,role,...}`；同步更新必要的资源清单/文档，不扩大到小图标。

**验收**：删除前静态引用审计无待删除路径消费者；目标资源在 verified snapshot 中可验证；插件导入/启动/无 snapshot 降级不抛 `FileNotFoundError`；未删除的 bootstrap 资源有清单和理由。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 12 — 资源删除与体积集中检查 `[pending]`

**类型**：集中检查-debug（Task 10–11）。

**检查**：运行全量静态路径/逻辑 key 搜索、目标测试/compile/lint/加载检查，构建真实市场发布包并记录体积；检查 `<=8 MiB`、`<=12 MiB`、`<16 MiB` 判定与最大剩余文件，发现回归或超标就追加最小修复/下一批纹理迁移 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 13 — README 与资源使用/维护文档同步 `[pending]`

**目标**：同步首次安装“建议执行同步资源”提示和当前资源边界、降级语义、维护/回滚说明。

**范围**：`README.md`、`docs/usage/resources.md`、必要的 `docs/dev/maintenance.md`、`docs/project/architecture.md`；不创建无关文档。

**验收**：README `> [!IMPORTANT]` 明确建议、非强制；文档描述 verified snapshot/bootstrap/placeholder/incomplete、首次同步、无重启刷新、资源仓库先行和回滚；不承诺不存在的 CI 或自动同步。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 14 — 无 snapshot / 完整 snapshot / 同步刷新运行期验证 `[pending]`

**目标**：用现有 fixture/fake 或本地可验证资源执行两种 snapshot 场景和同步后刷新冒烟，不访问真实生产账号，不提交资源内容。

**范围**：资源/generation/renderer 测试、插件加载检查、必要的最小运行脚本；不自动同步、不修改生产数据。

**验收**：无 verified snapshot 可启动、基础命令可执行、图片命令不因缺失资源崩溃并产生 `incomplete`；完整 snapshot 恢复主要渲染；发布新 generation 后无需重启使用新资源；取消/失败/非 2xx 等现有错误语义未被吞掉。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 15 — 运行期、文档、安全与回滚集中检查 `[pending]`

**类型**：集中检查-debug（Task 13–14）。

**检查**：核对规格偏差、静态引用/死代码、依赖和敏感信息、运行期数据目录、并发/缓存/manifest 一致性、README/docs、回滚路径和两个仓库交付顺序；发现问题追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填（如无则写“无”）。
- 剩余风险：待填。

## Task 16 — 最终发布包测量与证据收口 `[pending]`

**目标**：按真实市场提交方式生成最终插件包，记录体积、构成和阈值结论，确保没有完整大字体副本或私有文件。

**范围**：既有打包脚本/构建产物、`git ls-files`/归档内容、相关验证日志；不新增 CI。

**验收**：包可复现；字节数/MiB 明确；`<=8 MiB` 或有理由的 `<=12 MiB`，且 `<16 MiB`；最大剩余文件列出并说明保留理由；静态路径与测试证据附在 task 记录。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 17 — Goal 终审与完成登记 `[pending]`

**类型**：终审。

**检查**：从 C 端体验、代码质量、资源安全、manifest/generation、缓存刷新、无/有 snapshot、错误处理、测试覆盖、构建产物、文档和回滚角度进行最大范围复查。所有已知高风险问题必须修复或明确阻塞；确认 tasks.md 所有 task 已完成/阻塞并填写证据后，登记 goal 完成。

- 实际检查：待填。
- 验证证据：待填。
- 阻塞/低风险事项：待填。
- 最终报告要点：待填。
